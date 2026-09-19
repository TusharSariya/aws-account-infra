#!/usr/bin/env python3
"""Create a scoped Proxmox API identity over trusted SSH; save its token privately.
Run locally with --ssh-target pointing to an existing trusted root SSH host.
Never invoke the internal --remote mode interactively: it returns a secret.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

USER = 'homelab-tofu@pve'
TOKEN = 'provider'
ROLES = {
    'HomelabTofuHost': 'Sys.Audit Sys.Modify',
    'HomelabTofuVM': 'VM.Allocate VM.Audit VM.Config.CDROM VM.Config.CPU VM.Config.Disk VM.Config.HWType VM.Config.Memory VM.Config.Network VM.Config.Options VM.PowerMgmt VM.GuestAgent.Audit',
    'HomelabTofuStorage': 'Datastore.Audit Datastore.AllocateSpace',
    'HomelabTofuISO': 'Datastore.Audit',
    'HomelabTofuNetwork': 'SDN.Use',
}
SCOPES = {
    '/': 'HomelabTofuHost',
    '/vms/100': 'HomelabTofuVM',
    '/vms/102': 'HomelabTofuVM',
    '/storage/local-lvm': 'HomelabTofuStorage',
    '/storage/local': 'HomelabTofuISO',
    '/sdn/zones/localnetwork/vmbr0': 'HomelabTofuNetwork',
}


def select_plan():
    global USER, ROLES, SCOPES
    USER = 'homelab-tofu-plan@pve'
    ROLES = {
        'HomelabTofuAudit': 'Sys.Audit',
        'HomelabTofuPlanVM': 'VM.Audit VM.GuestAgent.Audit VM.Config.Disk',
        'HomelabTofuISO': 'Datastore.Audit',
    }
    SCOPES = {
        '/': 'HomelabTofuAudit',
        '/vms/100': 'HomelabTofuPlanVM',
        '/vms/102': 'HomelabTofuPlanVM',
        '/storage/local': 'HomelabTofuISO',
        '/storage/local-lvm': 'HomelabTofuISO',
    }


def pve(*args):
    format_args = ['--output-format', 'json'] if 'list' in args or args[:3] == ('user', 'token', 'add') else []
    completed = subprocess.run(['pveum', *args, *format_args],
                               capture_output=True, text=True)
    if completed.returncode:
        # CLI diagnostics might contain token values. Do not echo them.
        raise RuntimeError('Proxmox identity command failed: ' + ' '.join(args[:2]))
    return json.loads(completed.stdout) if completed.stdout.strip() else None


def remote():
    if os.geteuid() != 0 or os.uname().nodename != 'pve':
        raise RuntimeError('Bootstrap requires root on pve')
    users = {u['userid']: u for u in pve('user', 'list')}
    if USER in users and not users[USER].get('enable', 0):
        raise RuntimeError('Existing bootstrap user is disabled; inspect first')
    if USER in users and pve('user', 'token', 'list', USER):
        raise RuntimeError('Existing tokens found; reuse private credentials or explicitly revoke before reissuing')
    roles = {r['roleid']: r for r in pve('role', 'list')}
    for name, privileges in ROLES.items():
        if name in roles and set(roles[name]['privs'].split(',')) != set(privileges.split()):
            raise RuntimeError('Existing role differs: ' + name)
    for acl in pve('acl', 'list'):
        if acl['ugid'] in (USER, USER + '!' + TOKEN):
            if SCOPES.get(acl['path']) != acl['roleid'] or not acl.get('propagate'):
                raise RuntimeError('Existing identity ACL differs; inspect before changing')
    if USER not in users:
        pve('user', 'add', USER, '--comment', 'OpenTofu for homelab VMs 100 and 102')
    for name, privileges in ROLES.items():
        if name not in roles:
            pve('role', 'add', name, '--privs', privileges)
    for path, role in SCOPES.items():
        pve('acl', 'modify', path, '--users', USER, '--roles', role, '--propagate', '1')
    token = pve('user', 'token', 'add', USER, TOKEN, '--privsep', '1',
                '--comment', 'Homelab OpenTofu API - reissue after loss')
    for path, role in SCOPES.items():
        pve('acl', 'modify', path, '--tokens', USER + '!' + TOKEN,
            '--roles', role, '--propagate', '1')
    print(json.dumps({'endpoint': 'https://pve.tail2f646b.ts.net/',
                      'api_token': token['full-tokenid'] + '=' + token['value']}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-target', default='root@10.0.0.224')
    parser.add_argument('--plan', '--read-only', dest='plan', action='store_true',
                        help='Create CI plan identity (includes VM.Config.Disk for volume inspection; not strictly read-only)')
    parser.add_argument('--output', type=Path,
                        default=None)
    args = parser.parse_args()
    if args.plan:
        select_plan()
    if args.output is None:
        args.output = Path.home() / '.config/aws-account-infra/proxmox' / ('plan-credentials.json' if args.plan else 'credentials.json')
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*', args.ssh_target):
        raise RuntimeError('Unsupported SSH target')
    os.umask(0o077)
    output = args.output.expanduser().absolute()
    repo = Path(__file__).resolve().parents[1]
    resolved = output.resolve()
    if resolved == repo or repo in resolved.parents:
        raise RuntimeError('Credentials must be outside the repository')
    output.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if output.parent.stat().st_uid != os.getuid() or output.parent.stat().st_mode & 0o077:
        raise RuntimeError('Credential directory must be owned by you with mode 0700')
    # Reserve the destination before mutating the host. Never overwrite a credential.
    with output.open('x', encoding='utf-8') as stream:
        result = subprocess.run(['ssh', '-T', '-o', 'BatchMode=yes', '-o',
                                 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
                                 args.ssh_target, 'python3', '-', '--remote', *(['--plan'] if args.plan else [])],
                                input=Path(__file__).read_text(), text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError('Remote bootstrap failed. Inspect user/roles/token metadata on pve; do not overwrite or automatically rotate. The reserved local file is empty.')
        credentials = json.loads(result.stdout)
        if not credentials.get('api_token', '').startswith(USER + '!' + TOKEN + '='):
            raise RuntimeError('Unexpected token response')
        json.dump(credentials, stream)
        stream.write('\n')
    print('Created scoped API identity; credential saved with mode 0600 at ' + str(output))
    print('No VM or disk created. Token values were not printed.')


if __name__ == '__main__':
    try:
        if sys.argv[1:] in (['--remote'], ['--remote', '--plan'], ['--remote', '--read-only']):
            if '--plan' in sys.argv or '--read-only' in sys.argv:
                select_plan()
            remote()
        else:
            main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print('Bootstrap failed: ' + (str(error) if isinstance(error, RuntimeError) else type(error).__name__), file=sys.stderr)
        sys.exit(1)
