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
                    or after.get('url') != 'https://cloud-images.ubuntu.com/releases/noble/release-20260911/ubuntu-24.04-server-cloudimg-amd64.img'
                    or after.get('content_type') != 'import'
                    or after.get('checksum_algorithm') != 'sha256'
                    or after.get('node_name') != 'pve' or after.get('datastore_id') != 'local'):
                raise ValueError('Unapproved CI image')
        elif address == RUNNER and change['actions'] == ['create']:
            approved_key = plan.get('variables', {}).get('ci_runner_ssh_public_key', {}).get('value')
            initialization = after.get('initialization', [])
            if (not approved_key or len(initialization) != 1
                    or initialization[0].get('user_account') != [{'username': 'ubuntu', 'password': None, 'keys': [approved_key]}]
                    or any(initialization[0].get(k) for k in ('user_data_file_id', 'network_data_file_id', 'vendor_data_file_id', 'meta_data_file_id'))):
                raise ValueError('Unapproved manager bootstrap identity')
            resources = plan.get('configuration', {}).get('root_module', {}).get('resources', [])
            config = next((r for r in resources if r.get('address') == RUNNER.replace('[0]', '')), {})
            disks = config.get('expressions', {}).get('disk', [])
            if len(disks) != 1 or disks[0].get('import_from', {}).get('references', []) != [IMAGE + '.id', IMAGE, IMAGE.replace('[0]', '')]:
                raise ValueError('Manager disk must import the approved image resource')
            if (after.get('vm_id') != 103 or after.get('name') != 'ci-runner-01'
                    or after.get('node_name') != 'pve'
                    or after.get('started') is not False or after.get('on_boot') is not False
                    or len(after['cpu']) != 1 or after['cpu'][0].get('sockets') != 1
                    or after['cpu'][0]['cores'] != 4 or after['cpu'][0]['limit'] != 4
                    or after['memory'][0]['dedicated'] != 16384 or after['memory'][0]['floating'] != 0
                    or len(after['disk']) != 1 or after['disk'][0]['size'] != 100
                    or after['disk'][0]['datastore_id'] != 'local-lvm'
                    or len(after['network_device']) != 1
                    or after['network_device'][0].get('bridge') != 'vmbr0'
                    or after['network_device'][0].get('model') != 'virtio'
                    or after['network_device'][0]['mac_address'].lower() != '02:42:00:00:01:05'):
                raise ValueError('Unapproved CI VM capacity or identity')
        else:
            raise ValueError('Unexpected infrastructure change: ' + address)
        changed.append(address)
    if set(changed) != {WORKER, RUNNER, IMAGE}:
        raise ValueError('Initial activation requires exactly the image, VM and worker resize')
    return changed


def guard_start(plan):
    """Only start/on-boot may change after independently verified worker recovery."""
    if plan.get('errored') or plan.get('complete') is False:
        raise ValueError('Incomplete or failed plan')
    changed = []
    for resource in plan.get('resource_changes', []):
        change = resource['change']
        if change['actions'] == ['no-op']:
            continue
        if resource['address'] != RUNNER or change['actions'] != ['update']:
            raise ValueError('Runner activation cannot change other infrastructure')
        expected = copy.deepcopy(change['before'])
        if expected.get('started') is not False or expected.get('on_boot') is not False:
            raise ValueError('Runner must initially be stopped with on-boot disabled')
        expected.update(started=True, on_boot=True)
        if expected != change['after']:
            raise ValueError('Runner activation exceeds start/on-boot allowance')
        changed.append(RUNNER)
    if changed != [RUNNER]:
        raise ValueError('Expected exactly one runner start update')
    return changed
