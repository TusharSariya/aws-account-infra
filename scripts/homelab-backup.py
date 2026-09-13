#!/usr/bin/env python3
"""Capture, encrypt/upload, or independently verify homelab recovery material."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

from talos_tools import VERSION, cli, private_dir

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / 'config/environments/talos/homelab'
STATE = Path.home() / '.config/aws-account-infra/talos/homelab'
BUCKET = 'homelab-recovery-992382747916-us-east-1'
KEY = 'etcd/latest.tar.gz.age'
ETCD_VERSION = 'v3.6.12'
ASSETS = {
    ('Darwin', 'arm64'): ('darwin-arm64.zip', 'f71b0e5d3a06d60c37a5e321d147d9202a80d8890303f9b1bb4fa156dc0e39d3'),
    ('Linux', 'x86_64'): ('linux-amd64.tar.gz', 'd2564bb50b58e52fbaf3bde4a9561a1d04e20cdc761f795580e4d615d5d41355'),
}
BOOTSTRAP_FILES = [
    '.config/aws-account-infra/talos/homelab/talos-secrets.yaml',
    '.config/aws-account-infra/talos/homelab/two-vm-20260912/talos-cp-01.machineconfig.yaml',
    '.config/aws-account-infra/talos/homelab/two-vm-20260912/talos-worker-01.machineconfig.yaml',
    '.config/aws-account-infra/talos/homelab/two-vm-20260912/talosconfig',
    'Backups/proxmox/pve/pve-empty-host-baseline-20260912T210507Z.tar.gz',
]


class BackupError(ValueError):
    """Only deliberate secret-free diagnostics may be printed."""


def run(command):
    env = {k: v for k, v in os.environ.items() if k != 'TALOS_SECRETS_B64'}
    result = subprocess.run(list(map(str, command)), env=env, capture_output=True, timeout=300)
    if result.returncode:
        raise BackupError('Private command failed: ' + Path(str(command[0])).name
                          + '; exit ' + str(result.returncode) + '; diagnostics suppressed')
    return result.stdout


def private_file(path):
    path = path.expanduser()
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise BackupError('Recovery input must be privately owned with mode 0600')
    return path


def verify_identity(secret):
    expected = json.loads((INPUTS / 'identity.json').read_text())['secrets_sha256']
    if hashlib.sha256(secret).hexdigest() != expected:
        raise BackupError('Original Talos identity fingerprint mismatch')


def verify_snapshot(contents):
    if len(contents) < 33 or hashlib.sha256(contents[:-32]).digest() != contents[-32:]:
        raise BackupError('Snapshot embedded integrity checksum mismatch')


def verified_download(url, digest):
    data = urllib.request.urlopen(url, timeout=120).read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise BackupError('Downloaded tool checksum mismatch')
    return data


def etcdutl(directory):
    suffix, digest = ASSETS[(platform.system(), platform.machine())]
    asset = f'etcd-{ETCD_VERSION}-{suffix}'
    data = verified_download(f'https://github.com/etcd-io/etcd/releases/download/{ETCD_VERSION}/{asset}', digest)
    if suffix.endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            binary = archive.read(next(n for n in archive.namelist() if n.endswith('/etcdutl')))
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            binary = archive.extractfile(next(n for n in archive.getnames() if n.endswith('/etcdutl'))).read()
    target = directory / 'etcdutl'
    target.write_bytes(binary)
    target.chmod(0o700)
    return target


def age_binary(directory, daily):
    if not daily:
        binary = shutil.which('age')
        if not binary:
            raise BackupError('Install age before interactive backup or independent verification')
        return binary
    if (platform.system(), platform.machine()) != ('Linux', 'x86_64'):
        raise BackupError('Daily CI encryption requires Linux amd64')
    data = verified_download('https://dl.filippo.io/age/v1.3.2?for=linux/amd64',
                             'cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        binary = archive.extractfile('age/age').read()
    target = directory / 'age'
    target.write_bytes(binary)
    target.chmod(0o700)
    return target


def capture(output, state_dir=STATE, talosconfig=None):
    """Generate once; reuse that original identity for snapshot and reconstruction."""
    if output.exists() or output.is_symlink():
        raise BackupError('Capture needs a new output directory outside Git')
    secret = private_file(state_dir / 'talos-secrets.yaml').read_bytes()
    verify_identity(secret)
    output = private_dir(output)
    (output / 'talos-secrets.yaml').write_bytes(secret)
    run([sys.executable, ROOT / 'scripts/homelab-talos-config.py', 'generate',
         '--state-dir', output, '--output', output / 'machine-configs'])
    config = private_file(talosconfig) if talosconfig else output / 'machine-configs/talosconfig'
    inventory = json.loads((ROOT / 'config/environments/proxmox/homelab/talos/cluster.json').read_text())
    snapshot = output / 'etcd.snapshot'
    run([cli(), '--talosconfig', config, '-n', inventory['talos_endpoint'], 'etcd', 'snapshot', snapshot])
    contents = snapshot.read_bytes()
    verify_snapshot(contents)
    with tempfile.TemporaryDirectory(prefix='etcd-tools-') as directory:
        status = json.loads(run([etcdutl(Path(directory)), 'snapshot', 'status', snapshot, '--write-out=json']))
    for relative in ['config/environments/talos/homelab', 'config/environments/proxmox/homelab/talos']:
        shutil.copytree(ROOT / relative, output / 'reconstruction' / relative)
    metadata = {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'cluster': inventory['name'], 'node': inventory['talos_endpoint'], 'api': inventory['endpoint'],
        'repository': 'https://github.com/TusharSariyaOrg/aws-account-infra',
        'git_commit': run(['git', '-C', ROOT, 'rev-parse', 'HEAD']).decode().strip(),
        'talos_version': VERSION, 'kubernetes_version': inventory['kubernetes_version'],
        'etcdutl_version': ETCD_VERSION, 'snapshot_status': status,
        'snapshot_bytes': len(contents), 'snapshot_sha256': hashlib.sha256(contents).hexdigest(),
        'embedded_checksum_verified': True,
        'terraform_state_bucket': 'tofu-state-992382747916-us-east-1',
        'terraform_state_keys': ['talos/homelab/terraform.tfstate', 'proxmox/homelab/terraform.tfstate'],
        'scope': 'etcd, original Talos identity, regenerated machine configs and public reconstruction inputs; no application volume data',
    }
    (output / 'snapshot-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    return metadata


def recipient():
    value = (INPUTS / 'backup-recipient.txt').read_text().strip()
    if not re.fullmatch(r'age1[0-9a-z]{58}', value):
        raise BackupError('Expected one age public recipient')
    return value


def aws_command(daily=False):
    command = ['aws', '--region', 'us-east-1'] + ([] if daily else ['--profile', 'admin'])
    if json.loads(run(command + ['sts', 'get-caller-identity']))['Account'] != '992382747916':
        raise BackupError('Unexpected AWS account')
    return command


def upload_verified(aws, encrypted, key, metadata):
    contents = encrypted.read_bytes()
    digest = hashlib.sha256(contents).digest()
    uploaded = json.loads(run(aws + ['s3api', 'put-object', '--bucket', BUCKET, '--key', key,
        '--body', encrypted, '--checksum-algorithm', 'SHA256',
        '--checksum-sha256', base64.b64encode(digest).decode(), '--metadata', json.dumps(metadata)]))
    version = uploaded.get('VersionId')
    if not isinstance(version, str) or not version.strip() or version == 'null':
        raise BackupError('S3 did not return a non-null VersionId')
    downloaded = encrypted.parent / 'downloaded.tar.gz.age'
    run(aws + ['s3api', 'get-object', '--bucket', BUCKET, '--key', key, '--version-id', version,
               '--checksum-mode', 'ENABLED', downloaded])
    if contents != downloaded.read_bytes():
        raise BackupError('Exact-version ciphertext comparison failed')
    return {'bucket': BUCKET, 'key': key, 'version_id': version, 'ciphertext_sha256': digest.hex()}


def heartbeat(aws):
    run(aws + ['cloudwatch', 'put-metric-data', '--namespace', 'Homelab/Recovery',
               '--metric-data', json.dumps([{'MetricName': 'EtcdBackupSuccess',
               'Dimensions': [{'Name': 'Cluster', 'Value': 'homelab'}], 'Value': 1, 'Unit': 'Count'}])])


def interactive_age(command):
    if not sys.stdin.isatty():
        raise BackupError('Run manual passphrase operations in an interactive terminal; never source the script')
    # age reads its passphrase directly from the terminal; never store it in Python or CI.
    if subprocess.run(list(map(str, command))).returncode:
        raise BackupError('Interactive age operation failed')


def backup(mode):
    daily = mode == 'daily'
    if daily and os.environ.get('GITHUB_ACTIONS') != 'true':
        raise BackupError('Daily uploads run through GitHub CI')
    if not daily and not sys.stdin.isatty():
        raise BackupError('Manual backup requires an interactive terminal')
    aws = aws_command(daily)
    public_key = recipient() if daily else None
    retained = None
    if not daily:
        parent = private_dir(Path.home() / 'Backups/homelab-recovery')
        retained = Path(tempfile.mkdtemp(prefix='backup.', dir=parent))
    # All plaintext always lives in a disposable private directory, including on failure.
    with tempfile.TemporaryDirectory(prefix='homelab-backup-') as temporary:
        work = Path(temporary)
        encrypted_dir = work if daily else retained
        metadata = {}
        packed = work / 'source.tar.gz'
        if mode == 'bootstrap':
            verify_identity(private_file(Path.home() / BOOTSTRAP_FILES[0]).read_bytes())
            with tarfile.open(packed, 'w:gz') as archive:
                for relative in BOOTSTRAP_FILES:
                    source = private_file(Path.home() / relative)
                    archive.add(source, arcname=relative)
            archive_format = 'bootstrap-home-v1'
        else:
            source = STATE
            if daily:
                secret = base64.b64decode(os.environ.get('TALOS_SECRETS_B64', ''), validate=True)
                verify_identity(secret)
                (work / 'talos-secrets.yaml').write_bytes(secret)
                source = work
            bundle = work / 'bundle'
            metadata = capture(bundle, source)
            with tarfile.open(packed, 'w:gz') as archive:
                archive.add(bundle, arcname='homelab' if daily else '.')
            archive_format = 'etcd-homelab-v1' if daily else 'etcd-dot-v1'
        encrypted = encrypted_dir / 'backup.tar.gz.age'
        age = age_binary(work, daily)
        if daily:
            run([age, '-r', public_key, '-o', encrypted, packed])
            key = KEY
        else:
            print('Encrypting with your independently saved passphrase.', flush=True)
            interactive_age([age, '-p', '-o', encrypted, packed])
            prefix = 'bootstrap/etcd' if mode == 'etcd' else 'bootstrap'
            key = prefix + '/' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + retained.name + '.tar.gz.age'
        receipt = upload_verified(aws, encrypted, key, {
            'snapshot-created-at': metadata['created_at'], 'recipient': public_key} if daily else {})
        receipt.update({'receipt_schema': 1, 'archive_format': archive_format,
                        'encryption': 'age-recipient' if daily else 'age-passphrase',
                        'git_commit': run(['git', '-C', ROOT, 'rev-parse', 'HEAD']).decode().strip()})
        if metadata:
            receipt.update({'snapshot_created_at': metadata['created_at'], 'snapshot_status': metadata['snapshot_status']})
        if daily:
            # Publication follows complete capture, encryption, exact-version upload/readback only.
            heartbeat(aws)
            receipt['verified'] = 'embedded snapshot hash and exact-version encrypted readback'
        else:
            # Retain the exact uploaded version even if the decrypt rehearsal fails.
            receipt['verified'] = 'exact-version ciphertext; decryption pending'
            (retained / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            (retained / 'receipt.txt').write_text(f"s3://{BUCKET}/{key}\nVersion: {receipt['version_id']}\nDecryption pending\n")
            print('Receipt directory: ' + str(retained), flush=True)
            restored = work / 'restored.tar.gz'
            interactive_age([age, '-d', '-o', restored, encrypted_dir / 'downloaded.tar.gz.age'])
            if packed.read_bytes() != restored.read_bytes():
                raise BackupError('Decrypted archive differs from source')
            receipt['verified'] = 'exact-version ciphertext and decrypted source archive equality'
            (retained / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            (retained / 'receipt.txt').write_text(f"s3://{BUCKET}/{key}\nVersion: {receipt['version_id']}\nPASS: encrypted backup restored exactly\n")
            if metadata:
                (retained / 'snapshot-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
            print('Receipt directory: ' + str(retained))
        print(json.dumps(receipt, indent=2))
        return receipt


def read_receipt(path):
    text = path.read_text()
    try:
        receipt = json.loads(text)
    except json.JSONDecodeError:
        location = re.search(r'^s3://([^/]+)/([^\n]+)$', text, re.MULTILINE)
        version = re.search(r'^Version: ([^\n]+)$', text, re.MULTILINE)
        if not location or not version:
            raise BackupError('Expected a JSON receipt or original s3:// / Version: text receipt')
        receipt = {'bucket': location[1], 'key': location[2], 'version_id': version[1]}
    if (receipt.get('bucket') != BUCKET or not isinstance(receipt.get('version_id'), str)
            or not receipt['version_id'].strip() or receipt['version_id'] == 'null'
            or not (receipt.get('key') == KEY or receipt.get('key', '').startswith('bootstrap/'))):
        raise BackupError('Receipt must identify an exact version in the approved recovery backup set')
    return receipt


def inspect_archive(packed, work):
    # Read members in memory; never unpack caller-supplied paths or links to disk.
    with tarfile.open(packed, 'r:gz') as archive:
        files = {}
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or member.issym() or member.islnk():
                raise BackupError('Unsafe backup archive member')
            if member.isfile():
                if str(path) in files:
                    raise BackupError('Duplicate backup archive member')
                files[str(path)] = member
        for prefix, fmt in [('homelab/', 'etcd-homelab-v1'), ('', 'etcd-dot-v1')]:
            if prefix + 'etcd.snapshot' not in files:
                continue
            def read(name):
                return archive.extractfile(files[prefix + name]).read()
            snapshot = read('etcd.snapshot')
            verify_snapshot(snapshot)
            verify_identity(read('talos-secrets.yaml'))
            metadata = json.loads(read('snapshot-metadata.json'))
            if hashlib.sha256(snapshot).hexdigest() != metadata['snapshot_sha256']:
                raise BackupError('Snapshot metadata digest mismatch')
            target = work / 'verified.snapshot'
            target.write_bytes(snapshot)
            status = json.loads(run([etcdutl(work), 'snapshot', 'status', target, '--write-out=json']))
            if status != metadata['snapshot_status']:
                raise BackupError('Snapshot status differs from archived metadata')
            return {'archive_format': fmt, 'snapshot_status': status, 'embedded_checksum_verified': True}
        if not all(path in files for path in BOOTSTRAP_FILES):
            raise BackupError('Unrecognized or incomplete bootstrap archive')
        verify_identity(archive.extractfile(files[BOOTSTRAP_FILES[0]]).read())
        return {'archive_format': 'bootstrap-home-v1', 'original_identity_verified': True}


def verify(receipt_path, identity=None):
    receipt = read_receipt(receipt_path)
    if identity:
        identity = private_file(identity)
    elif not sys.stdin.isatty():
        raise BackupError('Passphrase verification requires an interactive terminal')
    aws = aws_command()
    with tempfile.TemporaryDirectory(prefix='homelab-verify-') as directory:
        work = Path(directory)
        encrypted, packed = work / 'downloaded.age', work / 'restored.tar.gz'
        run(aws + ['s3api', 'get-object', '--bucket', receipt['bucket'], '--key', receipt['key'],
                   '--version-id', receipt['version_id'], '--checksum-mode', 'ENABLED', encrypted])
        if receipt.get('ciphertext_sha256') and hashlib.sha256(encrypted.read_bytes()).hexdigest() != receipt['ciphertext_sha256']:
            raise BackupError('Receipt ciphertext digest mismatch')
        age = age_binary(work, False)
        if identity:
            run([age, '-d', '-i', identity, '-o', packed, encrypted])
        else:
            interactive_age([age, '-d', '-o', packed, encrypted])
        result = inspect_archive(packed, work)
        if receipt.get('archive_format') and receipt['archive_format'] != result['archive_format']:
            raise BackupError('Archive layout differs from receipt')
        print(json.dumps({'bucket': receipt['bucket'], 'key': receipt['key'],
                          'version_id': receipt['version_id'], **result,
                          'verified': 'decryption and archive integrity; not a cluster restore'}, indent=2))
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    c = commands.add_parser('capture')
    c.add_argument('--output', required=True, type=Path)
    c.add_argument('--state-dir', type=Path, default=STATE)
    c.add_argument('--talosconfig', type=Path)
    b = commands.add_parser('backup')
    b.add_argument('--mode', choices=['daily', 'etcd', 'bootstrap'], default='daily')
    v = commands.add_parser('verify')
    v.add_argument('--receipt', required=True, type=Path)
    v.add_argument('--identity', type=Path)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        if args.action == 'capture':
            metadata = capture(args.output.expanduser(), args.state_dir.expanduser(), args.talosconfig)
            print(json.dumps({'output': str(args.output), 'snapshot_status': metadata['snapshot_status'],
                              'snapshot_bytes': metadata['snapshot_bytes'], 'embedded_checksum_verified': True}, indent=2))
        elif args.action == 'backup':
            backup(args.mode)
        else:
            verify(args.receipt.expanduser(), args.identity)
    except Exception as error:
        print(str(error) if isinstance(error, BackupError) else
              'Backup operation failed (' + type(error).__name__ + '); private diagnostics suppressed', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
