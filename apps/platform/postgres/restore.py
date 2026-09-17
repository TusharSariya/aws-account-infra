"""Restore one exact S3 version into a separate, empty PostgreSQL 18 instance."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

import boto3
import psycopg
from psycopg import sql
from backup import AWS_CONFIG, BackupError, KEY, MAX_ARCHIVE, MAX_DUMP, bounded_copy, digest_file


def unpack(path, directory):
    expected = {'apps.dump', 'roles.json', 'restore.json', 'checksums.json'}
    with tarfile.open(path, 'r:gz') as archive:
        members = archive.getmembers()
        if {m.name for m in members} != expected or len(members) != len(expected):
            raise BackupError('Unexpected archive members')
        for member in members:
            if not member.isfile() or member.size > (MAX_DUMP if member.name == 'apps.dump' else 1024 ** 2):
                raise BackupError('Unsafe or oversized archive member')
            with archive.extractfile(member) as source, (directory / member.name).open('xb') as target:
                bounded_copy(source, target, member.size)
    checksums = json.loads((directory / 'checksums.json').read_text())
    if set(checksums) != expected - {'checksums.json'}:
        raise BackupError('Incomplete checksum manifest')
    for name, checksum in checksums.items():
        if digest_file(directory / name) != checksum:
            raise BackupError('Archive member checksum mismatch')
    metadata = json.loads((directory / 'restore.json').read_text())
    if metadata['format'] != 1 or metadata['database'] != 'apps' or not metadata['server_version'].startswith('18.'):
        raise BackupError('Unsupported restore metadata')
    return metadata, json.loads((directory / 'roles.json').read_text())


def restore_roles(connection, inventory, passwords):
    if set(passwords) != {r['name'] for r in inventory if r['login']}:
        raise BackupError('Supply a fresh password for every archived login')
    for role in inventory:
        name = role['name']
        if not re.fullmatch(r'app_[a-z0-9_]{1,50}|apps_owner|apps_backup', name):
            raise BackupError('Unreviewed role name')
        if role['bypassrls'] and name != 'apps_backup':
            raise BackupError('Unexpected RLS bypass')
        if role['login'] and len(passwords[name]) < 32:
            raise BackupError('Fresh role passwords must contain at least 32 characters')
        statement = sql.SQL('CREATE ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION {} {} CONNECTION LIMIT {}').format(
            sql.Identifier(name), sql.SQL('LOGIN' if role['login'] else 'NOLOGIN'),
            sql.SQL('BYPASSRLS' if role['bypassrls'] else 'NOBYPASSRLS'), sql.Literal(role['connection_limit']))
        connection.execute(statement)
        if role['login']:
            # Hash client-side; never send a cleartext password in a SQL statement.
            encoded = connection.pgconn.encrypt_password(passwords[name].encode(), name.encode(), b'scram-sha-256')
            connection.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(name), sql.Literal(encoded.decode())))
        for setting in role['settings']:
            key, value = setting.split('=', 1)
            connection.execute(sql.SQL('ALTER ROLE {} SET {} TO {}').format(
                sql.Identifier(name), sql.Identifier(key), sql.Literal(value)))
    allowed = {r['name'] for r in inventory} | {'pg_read_all_data'}
    for role in inventory:
        for parent, admin, inherit, set_role in role['memberships']:
            if parent not in allowed:
                raise BackupError('Unreviewed parent role')
            connection.execute(sql.SQL('GRANT {} TO {} WITH ADMIN {}, INHERIT {}, SET {}').format(
                sql.Identifier(parent), sql.Identifier(role['name']),
                *[sql.SQL('TRUE' if b else 'FALSE') for b in (admin, inherit, set_role)]))


def restore(directory, passwords):
    metadata, inventory = unpack(directory / 'backup.tar.gz', directory)
    if os.environ.get('PGDATABASE') != 'postgres' or 'apps-db-rw' in os.environ.get('PGHOST', ''):
        raise BackupError('Connect to postgres on a separate disposable instance')
    with psycopg.connect('', autocommit=True) as connection:
        version, system_id = connection.execute(
            "SELECT current_setting('server_version'), system_identifier::text FROM pg_control_system()").fetchone()
        if not version.startswith('18.') or system_id == metadata['system_identifier']:
            raise BackupError('Restore target must be a different PostgreSQL 18 instance')
        if connection.execute("SELECT 1 FROM pg_database WHERE datname='apps'").fetchone():
            raise BackupError('Refusing to overwrite an existing apps database')
        with connection.transaction():
            restore_roles(connection, inventory, passwords)
    result = subprocess.run(['pg_restore', '--create', '--exit-on-error', '--no-password',
                             '--dbname=postgres', str(directory / 'apps.dump')], capture_output=True)
    if result.returncode:
        raise BackupError('Restore failed; dispose of the target instance before retrying')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bucket', required=True)
    parser.add_argument('--version-id', required=True)
    parser.add_argument('--passwords', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.version_id == 'null' or args.passwords.stat().st_mode & 0o077:
            raise BackupError('Exact version and private fresh-password file required')
        s3 = boto3.Session(region_name='us-east-1').client('s3', config=AWS_CONFIG)
        with tempfile.TemporaryDirectory(dir=args.scratch) as name:
            directory = Path(name)
            obj = s3.get_object(Bucket=args.bucket, Key=KEY, VersionId=args.version_id)
            with contextlib.closing(obj['Body']) as body, (directory / 'backup.tar.gz').open('xb') as target:
                checksum, _ = bounded_copy(body, target, MAX_ARCHIVE)
            if obj.get('VersionId') != args.version_id or checksum != obj.get('Metadata', {}).get('sha256'):
                raise BackupError('Exact version or archive checksum mismatch')
            restore(directory, json.loads(args.passwords.read_text()))
        print(json.dumps(dict(restored_version=args.version_id, status='restored; verify data and permissions')))
        return 0
    except Exception:
        print('Restore refused or failed; production was not selected. Private diagnostics suppressed.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
