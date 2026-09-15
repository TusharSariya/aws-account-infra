"""Narrow plan allowance for initial CI hardware activation, never a general bypass."""
import copy

WORKER = 'proxmox_virtual_environment_vm.guest["talos-worker-01"]'
RUNNER = 'proxmox_virtual_environment_vm.ci_runner[0]'
IMAGE = 'proxmox_virtual_environment_download_file.ci_ubuntu[0]'


def guard(plan):
    if plan.get('errored') or plan.get('complete') is False:
        raise ValueError('Incomplete or failed plan')
    changed = []
    for resource in plan.get('resource_changes', []):
        change = resource['change']
        if change['actions'] == ['no-op']:
            continue
        address = resource['address']
        before, after = change.get('before'), change.get('after')
        if address == WORKER and change['actions'] == ['update']:
            expected = copy.deepcopy(before)
            if expected['memory'][0]['dedicated'] != 172 * 1024:
                raise ValueError('Worker no longer has the expected original RAM')
            expected['memory'][0]['dedicated'] = 156 * 1024
            if expected != after:
                raise ValueError('Worker change exceeds the exact RAM allowance')
        elif address == IMAGE and change['actions'] == ['create']:
            if (after.get('checksum') != '612b2c0cc1bc413a6cb8c38fd611794caf0f2b436c50013d8b3794db12ad7354'
                    or after.get('checksum_algorithm') != 'sha256'
                    or after.get('node_name') != 'pve' or after.get('datastore_id') != 'local'):
                raise ValueError('Unapproved CI image')
        elif address == RUNNER and change['actions'] == ['create']:
            if (after.get('vm_id') != 103 or after.get('name') != 'ci-runner-01'
                    or after.get('node_name') != 'pve'
                    or after['cpu'][0]['cores'] != 4 or after['cpu'][0]['limit'] != 4
                    or after['memory'][0]['dedicated'] != 16384 or after['memory'][0]['floating'] != 0
                    or len(after['disk']) != 1 or after['disk'][0]['size'] != 100
                    or after['disk'][0]['datastore_id'] != 'local-lvm'
                    or after['network_device'][0]['mac_address'].lower() != '02:42:00:00:01:03'):
                raise ValueError('Unapproved CI VM capacity or identity')
        else:
            raise ValueError('Unexpected infrastructure change: ' + address)
        changed.append(address)
    if set(changed) != {WORKER, RUNNER, IMAGE}:
        raise ValueError('Initial activation requires exactly the image, VM and worker resize')
    return changed
