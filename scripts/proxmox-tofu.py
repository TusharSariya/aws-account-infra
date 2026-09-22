#!/usr/bin/env python3
"""Initialize, validate or preview the Proxmox root with private credentials.
This helper cannot apply or save an executable plan.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'validate', 'check', 'plan'])
    parser.add_argument('--credentials', type=Path,
                        default=Path.home() / '.config/aws-account-infra/proxmox/credentials.json')
    args = parser.parse_args()
    os.umask(0o077)
    path = args.credentials.expanduser()
    if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError('Credentials must be a private file owned by you (0600)')
    credentials = json.loads(path.read_text())
    endpoint = credentials['endpoint']
    if endpoint != 'https://pve.tail2f646b.ts.net/':
        raise ValueError('Unexpected API endpoint; review identity and TLS before changing it')
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('TF_CLI_ARGS', 'TF_LOG', 'TOFU_LOG'))}
    for key in ('PROXMOX_VE_USERNAME', 'PROXMOX_VE_PASSWORD', 'PROXMOX_VE_AUTH_TICKET',
                'PROXMOX_VE_CSRF_PREVENTION_TOKEN', 'PROXMOX_VE_INSECURE'):
        env.pop(key, None)
    env['PROXMOX_VE_ENDPOINT'] = endpoint
    env['PROXMOX_VE_API_TOKEN'] = credentials['api_token']
    env.setdefault('AWS_PROFILE', 'admin')
    if args.action == 'check':
        for route in ('version', 'nodes', 'nodes/pve/storage', 'access/permissions?path=/vms/100',
                      'access/permissions?path=/vms/102', 'access/permissions?path=/vms/101'):
            request = urllib.request.Request(endpoint + 'api2/json/' + route,
                        headers={'Authorization': 'PVEAPIToken=' + credentials['api_token']})
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.load(response)['data']
            if route.startswith('access/permissions'):
                permissions = {priv for values in data.values() for priv in values}
                expected = route.endswith('/102')
                if ('VM.Allocate' in permissions) != expected:
                    raise ValueError('VM allocation scope differs from the approved IDs')
            print('PASS: authenticated HTTPS ' + route)
        return
    command = ['tofu', '-chdir=' + str(ROOT / 'live/proxmox/homelab'), args.action]
    if args.action == 'init':
        command += ['-input=false', '-lockfile=readonly']
    if args.action == 'plan':
        # Preview the proposed change assuming later approval, without an apply artifact.
        command += ['-input=false', '-lock-timeout=30s',
                    '-var-file=' + str(ROOT / 'config/environments/proxmox/homelab/vms.tfvars'),
                    '-var=vm_creation_approved=true']
        print('Speculative preview assumes future VM approval. No apply or saved plan.', flush=True)
    raise SystemExit(subprocess.call(command, env=env))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print('Proxmox check failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
