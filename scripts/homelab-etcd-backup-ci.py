#!/usr/bin/env python3
"""Unattended encrypted etcd backup; only sanitized receipt data reaches CI logs."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BUCKET = 'homelab-recovery-992382747916-us-east-1'
KEY = 'etcd/latest.tar.gz.age'


def recipient():
    value = (ROOT / 'config/environments/talos/homelab/backup-recipient.txt').read_text().strip()
    if not re.fullmatch(r'age1[0-9a-z]{58}', value):
        raise ValueError('Expected one age public recipient')
    return value


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('Scheduled backup uploads run in GitHub Actions')
    os.umask(0o077)
    secret = base64.b64decode(os.environ['TALOS_SECRETS_B64'], validate=True)
    identity = json.loads((ROOT / 'config/environments/talos/homelab/identity.json').read_text())
    if hashlib.sha256(secret).hexdigest() != identity['secrets_sha256']:
        raise ValueError('Cluster identity fingerprint mismatch')
    public_key = recipient()
    env = {k: v for k, v in os.environ.items() if k != 'TALOS_SECRETS_B64'}

    def run(command):
        completed = subprocess.run(list(map(str, command)), env=env, capture_output=True, timeout=300)
        if completed.returncode:
            raise RuntimeError('Backup command failed: ' + Path(str(command[0])).name + '; private diagnostics suppressed')
        return completed.stdout

    aws = ['aws', '--region', 'us-east-1']
    account = json.loads(run(aws + ['sts', 'get-caller-identity']))['Account']
    if account != '992382747916':
        raise ValueError('Unexpected AWS account')
    with tempfile.TemporaryDirectory(prefix='etcd-ci-') as directory:
        private = Path(directory)
        (private / 'talos-secrets.yaml').write_bytes(secret)
        run([sys.executable, ROOT / 'scripts/homelab-talos-config.py', 'generate',
             '--state-dir', private, '--output', private / 'generated'])
        bundle = private / 'bundle'
        run([sys.executable, ROOT / 'scripts/homelab-etcd-snapshot.py', '--output', bundle,
             '--state-dir', private, '--talosconfig', private / 'generated/talosconfig'])
        metadata = json.loads((bundle / 'snapshot-metadata.json').read_text())
        packed = private / 'snapshot.tar.gz'
        with tarfile.open(packed, 'w:gz') as archive:
            archive.add(bundle, arcname='homelab')
        data = urllib.request.urlopen('https://dl.filippo.io/age/v1.3.2?for=linux/amd64', timeout=60).read()
        if hashlib.sha256(data).hexdigest() != 'cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10':
            raise ValueError('age download checksum mismatch')
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            binary = archive.extractfile('age/age').read()
        age = private / 'age'
        age.write_bytes(binary)
        age.chmod(0o700)
        encrypted = private / 'snapshot.tar.gz.age'
        run([age, '-r', public_key, '-o', encrypted, packed])
        digest = base64.b64encode(hashlib.sha256(encrypted.read_bytes()).digest()).decode()
        uploaded = json.loads(run(aws + ['s3api', 'put-object', '--bucket', BUCKET, '--key', KEY,
            '--body', encrypted, '--checksum-algorithm', 'SHA256', '--checksum-sha256', digest,
            '--metadata', json.dumps({'snapshot-created-at': metadata['created_at'], 'recipient': public_key})]))
        version = uploaded.get('VersionId')
        if not version or version == 'null':
            raise ValueError('S3 versioning did not return a version ID')
        downloaded = private / 'downloaded.age'
        run(aws + ['s3api', 'get-object', '--bucket', BUCKET, '--key', KEY, '--version-id', version,
                   '--checksum-mode', 'ENABLED', downloaded])
        if encrypted.read_bytes() != downloaded.read_bytes():
            raise ValueError('Exact S3 version ciphertext comparison failed')
        # Only a complete snapshot/encryption/upload/readback may publish success.
        run(aws + ['cloudwatch', 'put-metric-data', '--namespace', 'Homelab/Recovery',
                   '--metric-data', json.dumps([{'MetricName': 'EtcdBackupSuccess',
                       'Dimensions': [{'Name': 'Cluster', 'Value': 'homelab'}], 'Value': 1, 'Unit': 'Count'}])])
        print(json.dumps({'bucket': BUCKET, 'key': KEY, 'version_id': version,
                          'snapshot_created_at': metadata['created_at'],
                          'snapshot_status': metadata['snapshot_status'],
                          'ciphertext_sha256': hashlib.sha256(encrypted.read_bytes()).hexdigest(),
                          'verified': 'embedded snapshot hash and exact-version encrypted readback'}, indent=2))
        print('PASS: encrypted daily etcd backup uploaded, verified and heartbeat recorded')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Daily backup failed ({type(error).__name__}); no success heartbeat emitted.', file=sys.stderr)
        sys.exit(1)
