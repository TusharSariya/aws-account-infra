#!/usr/bin/env python3
"""Protected CI host reconciliation; only fixed repository files cross SSH."""
import base64
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SECRET_NAMES = ('CAPACITY_HOST_SSH_KEY', 'CAPACITY_HOST_CREDENTIALS_B64')


def write_ssh_key(path, value):
    # gh secret set's stdin path trims CR/LF. OpenSSH requires its final newline.
    path.write_text(value.rstrip('\r\n') + '\n')


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise ValueError('Reviewed main CI required')
    credentials = json.loads(base64.b64decode(os.environ['CAPACITY_HOST_CREDENTIALS_B64'], validate=True))
    if set(credentials) != {'config.json', 'server.crt', 'server.key', 'client-ca.crt'}:
        raise ValueError('Exact host credential bundle required')
    env = {key: value for key, value in os.environ.items() if key not in SECRET_NAMES}
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='capacity-host-') as directory:
        directory = Path(directory)
        key, known = directory / 'ssh-key', directory / 'known-hosts'
        write_ssh_key(key, os.environ['CAPACITY_HOST_SSH_KEY'])
        known.write_text(os.environ['CAPACITY_HOST_KNOWN_HOSTS'])
        ssh = ['ssh', '-i', str(key), '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
               '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known),
               '-o', 'ConnectTimeout=15', 'root@pve.tail2f646b.ts.net']
        def run(command, data=None):
            result = subprocess.run(ssh + [command], input=data, capture_output=True, env=env, timeout=180)
            if result.returncode:
                raise ValueError('Host reconciliation command failed; private output suppressed')
            return result.stdout.decode().strip()
        remote = run('umask 077 && mktemp -d /var/tmp/homelab-capacity.XXXXXXXX')
        if not re.fullmatch(r'/var/tmp/homelab-capacity\.[A-Za-z0-9]{8}', remote):
            raise ValueError('Unexpected private host workspace')
        try:
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode='w:gz') as tar:
                files = ['scripts/install-homelab-capacity.sh',
                         'apps/platform/storage/physical.py', 'apps/platform/storage/physical_server.py']
                files += [str(path.relative_to(ROOT)) for path in
                          sorted((ROOT / 'config/environments/proxmox/homelab/capacity').glob('*'))]
                for name in files:
                    tar.add(ROOT / name, arcname=name, recursive=False)
                for name, value in credentials.items():
                    data = value.encode()
                    member = tarfile.TarInfo('credentials/' + name)
                    member.size, member.mode = len(data), 0o600
                    tar.addfile(member, io.BytesIO(data))
            run('tar -xzf - -C ' + remote, archive.getvalue())
            run('bash ' + remote + '/scripts/install-homelab-capacity.sh ' + remote + '/credentials')
        finally:
            run('rm -rf -- ' + remote)
    print('PASS: reviewed host recipe reconciled and sampler/exporter services verified')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Capacity host reconciliation failed; credentials and private diagnostics suppressed', file=sys.stderr)
        sys.exit(1)
