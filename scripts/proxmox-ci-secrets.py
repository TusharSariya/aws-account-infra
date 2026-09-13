#!/usr/bin/env python3
"""Install existing private Proxmox tokens as GitHub prod environment secrets.
Requires authenticated gh with repository administration access. No token is printed.
"""
import json
import os
from pathlib import Path
import subprocess

REPOSITORY = 'TusharSariyaOrg/aws-account-infra'


def main():
    directory = Path.home() / '.config/aws-account-infra/proxmox'
    entries = (
        ('plan-credentials.json', 'homelab-tofu-plan@pve!provider=', 'PROXMOX_PLAN_API_TOKEN'),
        ('credentials.json', 'homelab-tofu@pve!provider=', 'PROXMOX_APPLY_API_TOKEN'),
    )
    credentials = []
    for filename, prefix, name in entries:
        path = directory / filename
        if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
            raise SystemExit('Expected a private credential file owned by this user')
        token = json.loads(path.read_text())['api_token']
        if not token.startswith(prefix):
            raise SystemExit('Unexpected token identity; no credentials uploaded')
        credentials.append((name, token))
    for name, token in credentials:
        result = subprocess.run(['gh', 'secret', 'set', name, '--env', 'prod',
                                 '--repo', REPOSITORY], input=token, text=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode:
            raise SystemExit('GitHub secret update failed for ' + name)
        print('Configured prod environment secret: ' + name)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit('Credential configuration failed: ' + type(error).__name__) from None
