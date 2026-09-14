#!/usr/bin/env python3
"""Explicit CI capture of all AI data, encrypted artifact and isolated restore proof."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

from lifecycle_session import Maintenance, ROOT, KUBECTL, apps, private_environment


def age_tools(directory):
    spec = importlib.util.spec_from_file_location('homelab_backup', ROOT / 'scripts/homelab-backup.py')
    backup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backup)
    payload = backup.verified_download('https://dl.filippo.io/age/v1.3.2?for=linux/amd64',
        'cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10')
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
        for name in ('age', 'age-keygen'):
            target = directory / name
            target.write_bytes(archive.extractfile('age/' + name).read())
            target.chmod(0o700)
    return directory / 'age', directory / 'age-keygen'


def pipe(source, destination, *, output=None):
    environment = private_environment()
    with subprocess.Popen(list(map(str, source)), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          env=environment) as first:
        try:
            with subprocess.Popen(list(map(str, destination)), stdin=first.stdout, stdout=output or subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, env=environment) as second:
                first.stdout.close()
                try:
                    data, _ = second.communicate(timeout=900)
                    initial = first.wait(timeout=30)
                except BaseException:
                    second.kill()
                    second.wait()
                    raise
                if initial or second.returncode:
                    raise apps.AppError('Encrypted application backup/restore stream failed')
        finally:
            if first.poll() is None:
                first.kill()
                first.wait()
    return data


def backup_restore(session, output):
    if output.exists() or output.is_symlink():
        raise apps.AppError('Backup output must be a new private directory')
    output.mkdir(mode=0o700)
    revision = session.off()
    snapshot = session.fixture('snapshot')
    try:
        inventory = json.loads(session.kube('-n', 'homelab-models', 'exec', snapshot, '--',
                                            'python', '-B', '/code/archive.py', 'inventory'))
        session.unchanged_off(revision)
        with tempfile.TemporaryDirectory(prefix='ai-backup-key-', dir=os.environ['RUNNER_TEMP']) as temporary:
            private = Path(temporary)
            age, keygen = age_tools(private)
            key = private / 'restore-key.txt'
            apps.run([keygen, '-o', key])
            key.chmod(0o600)
            ephemeral = apps.run([keygen, '-y', key]).decode().strip()
            recipient = (ROOT / 'config/environments/talos/homelab/backup-recipient.txt').read_text().strip()
            artifact = output / 'ai-data.tar.gz.age'
            pipe([KUBECTL, '-n', 'homelab-models', 'exec', snapshot, '--', 'python', '-B', '/code/archive.py', 'capture'],
                 [age, '-r', recipient, '-r', ephemeral, '-o', artifact])
            session.unchanged_off(revision)
            session.remove(snapshot)
            restore = session.fixture('restore')
            proof = json.loads(pipe([age, '-d', '-i', key, artifact],
                [KUBECTL, '-n', 'homelab-models', 'exec', '-i', restore, '--', 'python', '-B', '/code/archive.py', 'restore']))
            session.remove(restore)
            session.unchanged_off(revision)
        with artifact.open('rb') as source:
            checksum = hashlib.file_digest(source, 'sha256').hexdigest()
        evidence = {'run_id': os.environ['GITHUB_RUN_ID'], 'source_commit': apps.run(['git', 'rev-parse', 'HEAD']).decode().strip(),
                    'lifecycle_revision': revision, 'archive_sha256': checksum, 'source_inventory': inventory,
                    'isolated_restore': proof, 'scope': ['models', 'workspace', 'vector'],
                    'artifact_retention_days': 90, 'durable_copy_verified': False}
        (output / 'restore-proof.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print('PASS: encrypted full three-volume capture and isolated restore hashes/SQLite integrity', flush=True)
    except BaseException:
        # A failed capture or revision change must never leave an apparently valid artifact.
        for name in ('ai-data.tar.gz.age', 'restore-proof.json'):
            (output / name).unlink(missing_ok=True)
        raise
    finally:
        session.cleanup()


if __name__ == '__main__':
    os.umask(0o077)
    try:
        backup_restore(Maintenance(), Path(os.environ['AI_BACKUP_OUTPUT']))
    except Exception as error:
        raise SystemExit(str(error) if isinstance(error, apps.AppError) else 'Application backup/restore failed; private diagnostics suppressed') from None
