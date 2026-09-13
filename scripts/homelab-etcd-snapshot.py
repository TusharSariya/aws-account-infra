#!/usr/bin/env python3
"""Capture and inspect an etcd snapshot into a new private directory; no restore/apply."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ETCD_VERSION = 'v3.6.12'
ASSETS = {
    ('Darwin', 'arm64'): ('darwin-arm64.zip', 'f71b0e5d3a06d60c37a5e321d147d9202a80d8890303f9b1bb4fa156dc0e39d3'),
    ('Linux', 'x86_64'): ('linux-amd64.tar.gz', 'd2564bb50b58e52fbaf3bde4a9561a1d04e20cdc761f795580e4d615d5d41355'),
}


def run(command):
    result = subprocess.run(list(map(str, command)), capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError('Snapshot preparation command failed; output suppressed to protect recovery inputs')
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    output = args.output.expanduser().resolve()
    if output == ROOT or ROOT in output.parents or output.exists():
        raise ValueError('Use a new private output directory outside Git')
    source = Path.home() / '.config/aws-account-infra/talos/homelab'
    secrets = source / 'talos-secrets.yaml'
    talosconfig = source / 'two-vm-20260912/talosconfig'
    for path in (secrets, talosconfig):
        if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
            raise ValueError('Recovery inputs must be privately owned, mode 0600')
    identity = json.loads((ROOT / 'config/environments/talos/homelab/identity.json').read_text())
    if hashlib.sha256(secrets.read_bytes()).hexdigest() != identity['secrets_sha256']:
        raise ValueError('Cluster identity mismatch')
    spec = importlib.util.spec_from_file_location('generator', ROOT / 'scripts/homelab-talos-config.py')
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    cli = generator.cli()
    suffix, digest = ASSETS[(platform.system(), platform.machine())]
    asset = f'etcd-{ETCD_VERSION}-{suffix}'
    with tempfile.TemporaryDirectory(prefix='etcd-tools-') as temporary:
        data = urllib.request.urlopen(f'https://github.com/etcd-io/etcd/releases/download/{ETCD_VERSION}/{asset}', timeout=60).read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('etcd release archive checksum mismatch')
        if suffix.endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                name = next(n for n in archive.namelist() if n.endswith('/etcdutl'))
                binary = archive.read(name)
        else:
            with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
                name = next(n for n in archive.getnames() if n.endswith('/etcdutl'))
                binary = archive.extractfile(name).read()
        etcdutl = Path(temporary) / 'etcdutl'
        etcdutl.write_bytes(binary)
        etcdutl.chmod(0o700)
        output.mkdir(mode=0o700, parents=True)
        snapshot = output / 'etcd.snapshot'
        tc = [cli, '--talosconfig', talosconfig, '-n', '10.42.0.220']
        run(tc + ['etcd', 'snapshot', snapshot])
        status = json.loads(run([etcdutl, 'snapshot', 'status', snapshot, '--write-out=json']))
        # Talos/etcd snapshots append a SHA-256 integrity hash to the DB image.
        contents = snapshot.read_bytes()
        if len(contents) < 33 or hashlib.sha256(contents[:-32]).digest() != contents[-32:]:
            raise ValueError('Snapshot embedded integrity checksum mismatch')
        shutil.copyfile(secrets, output / 'talos-secrets.yaml')
        run([os.sys.executable, ROOT / 'scripts/homelab-talos-config.py', 'generate',
             '--state-dir', output, '--output', output / 'machine-configs'])
        for relative in ['config/environments/talos/homelab', 'config/environments/proxmox/homelab/talos']:
            shutil.copytree(ROOT / relative, output / 'reconstruction' / relative)
        metadata = {
            'created_at': datetime.now(timezone.utc).isoformat(),
            'cluster': 'homelab', 'node': '10.42.0.220', 'api': 'https://10.42.0.224:6443',
            'repository': 'https://github.com/TusharSariyaOrg/aws-account-infra',
            'git_commit': run(['git', '-C', ROOT, 'rev-parse', 'HEAD']).decode().strip(),
            'talos_version': 'v1.13.9', 'kubernetes_version': 'v1.36.3',
            'etcdutl_version': ETCD_VERSION, 'snapshot_status': status,
            'snapshot_bytes': len(contents), 'snapshot_sha256': hashlib.sha256(contents).hexdigest(),
            'embedded_checksum_verified': True,
            'terraform_state_bucket': 'tofu-state-992382747916-us-east-1',
            'terraform_state_keys': ['talos/homelab/terraform.tfstate', 'proxmox/homelab/terraform.tfstate'],
            'scope': 'etcd, original Talos identity, regenerated machine configs and public reconstruction inputs; no application volume data',
        }
        (output / 'snapshot-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
        print(json.dumps({'output': str(output), 'snapshot_status': status,
                          'snapshot_bytes': len(contents), 'embedded_checksum_verified': True}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Snapshot preparation failed ({type(error).__name__}); no upload or restore performed.', file=os.sys.stderr)
        raise SystemExit(1) from None
