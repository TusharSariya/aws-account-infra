#!/usr/bin/env python3
"""Verify CI's Proxmox identity over trusted HTTPS, without printing its token."""
import argparse
import json
import os
import sys
import urllib.request


def check_permissions(data, writable):
    def privileges(path):
        return {key for key, value in data.get(path, {}).items() if value}
    # PVE checks startup order against /, independently of VM.Config.Options.
    if writable and 'Sys.Modify' not in privileges('/'):
        raise ValueError('Apply token requires Sys.Modify at / for VM startup order')
    if not writable and privileges('/') - {'Sys.Audit'}:
        raise ValueError('Plan token has unexpected host permissions')
    for path in ('/vms/100', '/vms/102'):
        rights = privileges(path)
        if 'VM.Audit' not in rights or ('VM.Allocate' in rights) != writable:
            raise ValueError('Unexpected VM permissions')
        if not writable and rights - {'VM.Audit', 'VM.GuestAgent.Audit', 'Sys.Audit'}:
            raise ValueError('Plan token has unexpected VM permissions')
    if 'VM.Allocate' in privileges('/vms/101'):
        raise ValueError('Token can allocate an unrelated VM')
    for path in ('/storage/local', '/storage/local-lvm'):
        rights = privileges(path)
        if 'Datastore.Audit' not in rights:
            raise ValueError('Token cannot inspect storage')
        if not writable and rights - {'Datastore.Audit', 'Sys.Audit'}:
            raise ValueError('Plan token has unexpected storage permissions')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['plan', 'apply'])
    args = parser.parse_args()
    endpoint = os.environ.get('PROXMOX_VE_ENDPOINT', '')
    token = os.environ.get('PROXMOX_VE_API_TOKEN', '')
    if endpoint != 'https://pve.tail2f646b.ts.net/' or not token:
        raise ValueError('Missing or unexpected CI connection configuration')
    permissions = {}
    paths = ('/', '/vms/100', '/vms/102', '/vms/101', '/storage/local', '/storage/local-lvm')
    for route in ['version', 'nodes/pve/storage'] + ['access/permissions?path=' + p for p in paths]:
        request = urllib.request.Request(endpoint + 'api2/json/' + route,
                    headers={'Authorization': 'PVEAPIToken=' + token})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)['data']
        if route.startswith('access/permissions'):
            permissions[route.split('path=', 1)[1]] = {key: value for entry in data.values() for key, value in entry.items()}
    check_permissions(permissions, args.mode == 'apply')
    print('PASS: trusted HTTPS, authenticated storage discovery and ' + args.mode + ' token scope')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print('CI Proxmox preflight failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
