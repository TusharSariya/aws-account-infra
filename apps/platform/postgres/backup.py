"""Bounded logical archives and exact-version publication. No credential logging."""
import contextlib
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import uuid

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
import psycopg

KEY = 'apps-db/latest.tar.gz'
LOCK = 748930126
GIB = 1024 ** 3
MAX_DUMP = 30 * GIB
MAX_ARCHIVE = 32 * GIB
CHUNK = 8 * 1024 ** 2
AWS_CONFIG = Config(connect_timeout=10, read_timeout=60,
                    retries={'mode': 'standard', 'total_max_attempts': 4})
TRANSFER = TransferConfig(multipart_threshold=CHUNK, multipart_chunksize=CHUNK,
                          max_concurrency=2)


class BackupError(ValueError):
    pass


def digest_file(path):
    with open(path, 'rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def bounded_copy(source, target, limit):
    total = 0
    digest = hashlib.sha256()
    while block := source.read(CHUNK):
        total += len(block)
        if total > limit:
            raise BackupError('Archive exceeds reviewed scratch budget')
        digest.update(block)
        if target is not None:
            target.write(block)
    return digest.hexdigest(), total


def command_to_file(command, path, limit):
    # Stderr can contain database data or credentials; it must not enter logs.
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        try:
            with open(path, 'xb') as target:
                bounded_copy(process.stdout, target, limit)
            if process.wait() != 0:
                raise BackupError('Database export failed; latest not published')
        except BaseException:
            process.kill()
            process.wait()
            raise


def roles(connection):
    # pg_roles deliberately excludes password hashes (unlike pg_authid).
    names = connection.execute("""SELECT rolname, rolcanlogin, rolbypassrls, rolconnlimit, rolconfig
        FROM pg_roles WHERE rolname !~ '^pg_' AND rolname NOT IN
        ('postgres', 'streaming_replica', 'cnpg_pooler_pgbouncer') ORDER BY rolname""").fetchall()
    result = []
    for name, login, bypass, limit, settings in names:
        if not (name in ('apps_owner', 'apps_backup') or name.startswith('app_')):
            raise BackupError('Unreviewed database role; update role inventory before backup')
        if bypass and name != 'apps_backup':
            raise BackupError('Application role must not bypass RLS')
        memberships = connection.execute("""SELECT r.rolname, m.admin_option, m.inherit_option, m.set_option
            FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid
            JOIN pg_roles u ON u.oid=m.member WHERE u.rolname=%s ORDER BY r.rolname""", (name,)).fetchall()
        result.append(dict(name=name, login=login, bypassrls=bypass, connection_limit=limit,
                           settings=settings or [], memberships=memberships))
    return result


def archive(connection, directory):
    connection.execute('SELECT 1')  # Lock connection must still be alive.
    version, system_id = connection.execute(
        'SELECT current_setting(\'server_version\'), system_identifier::text FROM pg_control_system()').fetchone()
    if not version.startswith('18.'):
        raise BackupError('Expected PostgreSQL 18')
    inventory = roles(connection)
    command_to_file(['pg_dump', '--format=custom', '--create', '--no-password'],
                    directory / 'apps.dump', MAX_DUMP)
    # DDL/onboarding must share LOCK; detect changed inventory even if an operator bypassed it.
    if roles(connection) != inventory:
        raise BackupError('Role inventory changed during export')
    (directory / 'roles.json').write_text(json.dumps(inventory, sort_keys=True))
    (directory / 'restore.json').write_text(json.dumps(dict(format=1, database='apps',
        server_version=version, system_identifier=system_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        credentials='Fresh passwords required for every login; no passwords in archive')))
    files = ['apps.dump', 'roles.json', 'restore.json']
    (directory / 'checksums.json').write_text(json.dumps({name: digest_file(directory / name) for name in files}))
    output = directory / 'backup.tar.gz'
    # Bound output writes too, including pathological incompressible input.
    class BoundedWriter:
        def __init__(self, file):
            self.file, self.size = file, 0
        def write(self, block):
            self.size += len(block)
            if self.size > MAX_ARCHIVE:
                raise BackupError('Archive exceeds reviewed scratch budget')
            return self.file.write(block)
        def flush(self):
            self.file.flush()
    with output.open('xb') as target:
        with tarfile.open(fileobj=BoundedWriter(target), mode='w|gz') as bundle:
            for name in files + ['checksums.json']:
                bundle.add(directory / name, arcname=name, recursive=False)
    return output


def exact_version(response):
    version = response.get('VersionId')
    if not version or version == 'null':
        raise BackupError('Versioning must be enabled')
    return version


def verify_object(s3, bucket, key, version, expected):
    result = s3.get_object(Bucket=bucket, Key=key, VersionId=version)
    with contextlib.closing(result['Body']) as source:
        observed, _ = bounded_copy(source, None, MAX_ARCHIVE)
    if exact_version(result) != version or observed != expected:
        raise BackupError('S3 exact-version checksum mismatch')


def publish(s3, bucket, kms_key, path, check_lock):
    checksum = digest_file(path)
    staging = 'staging/' + str(uuid.uuid4()) + '.tar.gz'
    extra = dict(ServerSideEncryption='aws:kms', SSEKMSKeyId=kms_key,
                 Metadata={'sha256': checksum}, ContentType='application/gzip')
    s3.upload_file(str(path), bucket, staging, ExtraArgs=extra, Config=TRANSFER)
    staged = s3.head_object(Bucket=bucket, Key=staging)
    version = exact_version(staged)
    verify_object(s3, bucket, staging, version, checksum)
    check_lock()
    # Multipart copy supports >5 GiB and returns the exact completion VersionId.
    upload = s3.create_multipart_upload(Bucket=bucket, Key=KEY, **extra)['UploadId']
    args = dict(Bucket=bucket, Key=KEY, UploadId=upload)
    try:
        parts = []
        part_size = 64 * 1024 ** 2
        for number, start in enumerate(range(0, path.stat().st_size, part_size), 1):
            check_lock()
            copied = s3.upload_part_copy(**args, PartNumber=number,
                CopySource={'Bucket': bucket, 'Key': staging, 'VersionId': version},
                CopySourceRange=f'bytes={start}-{min(start + part_size, path.stat().st_size) - 1}')
            parts.append(dict(PartNumber=number, ETag=copied['CopyPartResult']['ETag']))
        check_lock()
        published = s3.complete_multipart_upload(**args, MultipartUpload={'Parts': parts})
    except BaseException:
        # No DeleteObject permission. Incomplete uploads also expire independently.
        s3.abort_multipart_upload(**args)
        raise
    current = exact_version(published)
    verify_object(s3, bucket, KEY, current, checksum)
    check_lock()
    if exact_version(s3.head_object(Bucket=bucket, Key=KEY)) != current:
        raise BackupError('Concurrent publisher changed latest')
    return dict(key=KEY, version_id=current, sha256=checksum, staging_version_id=version)


def metric(cloudwatch, name, value=1):
    cloudwatch.put_metric_data(Namespace='Homelab/Postgres', MetricData=[dict(
        MetricName=name, Value=value, Unit='Count', Dimensions=[dict(Name='Cluster', Value='apps-db')])])


def backup(s3, cw, scratch):
    scratch = Path(scratch)
    # Kernel lock on shared disk covers scheduled/manual jobs on the one worker,
    # even if the database connection dies. No expiring lease split-brain.
    with (scratch / '.backup.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Only this lock holder owns the fixed scratch workspace; clean failed runs.
        work = scratch / 'work'
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(mode=0o700)
        try:
            if shutil.disk_usage(scratch).free < 64 * GIB:
                raise BackupError('Need 64 GiB free scratch space')
            with psycopg.connect('', autocommit=True) as connection:
                if not connection.execute('SELECT pg_try_advisory_lock(%s)', (LOCK,)).fetchone()[0]:
                    raise BackupError('Database onboarding or another backup is active')
                path = archive(connection, work)
                result = publish(s3, os.environ['BACKUP_BUCKET'], os.environ['BACKUP_KMS_KEY'],
                                 path, lambda: connection.execute('SELECT 1'))
                metric(cw, 'BackupSuccess')
                print(json.dumps(result))
        finally:
            shutil.rmtree(work)


def main():
    os.umask(0o077)
    session = boto3.Session(region_name='us-east-1')
    cw = session.client('cloudwatch', config=AWS_CONFIG)
    try:
        expiry = subprocess.run(['openssl', 'x509', '-in', '/identity/client.crt', '-noout',
                                 '-checkend', '2592000'], capture_output=True, timeout=15)
        metric(cw, 'CertificateExpiring', int(expiry.returncode != 0))
        backup(session.client('s3', config=AWS_CONFIG), cw, '/scratch')
        return 0
    except Exception:
        # Top-level suppression prevents SDK/database diagnostics leaking credentials.
        try:
            metric(cw, 'BackupFailure')
        except Exception:
            pass  # Independent missing-heartbeat alarm still covers credential failure.
        print('Backup failed; no success heartbeat. Inspect protected diagnostics and retry.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
