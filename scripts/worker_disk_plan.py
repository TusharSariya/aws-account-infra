"""Exact allowlist for the authorized 100-to-128-GiB worker OS disk growth."""
from copy import deepcopy
from ci_runner_plan import WORKER
from ci_retirement_plan import unknown


def guard(plan):
    if plan.get('errored') or plan.get('complete') is False or plan.get('deferred_changes') or plan.get('resource_drift'):
        raise ValueError('Complete successful disk plan required')
    changed = []
    for resource in plan.get('resource_changes', []):
        change = resource['change']
        if change['actions'] == ['no-op']:
            continue
        if (resource['address'] != WORKER or resource.get('mode', 'managed') != 'managed'
                or change['actions'] != ['update'] or unknown(change.get('after_unknown'))):
            raise ValueError('Only an in-place worker OS disk expansion is allowed')
        expected = deepcopy(change['before'])
        if (expected.get('vm_id') != 102 or expected.get('node_name') != 'pve'
                or expected.get('name') != 'talos-worker-01'
                or expected.get('reboot_after_update') is not False
                or len(expected.get('disk', [])) != 2):
            raise ValueError('Worker identity or disk inventory differs')
        disks = {d['interface']: d for d in expected['disk']}
        for interface, size, identity in [('scsi0', 100, 'vm-102-disk-1'), ('scsi1', 1200, 'vm-102-disk-2')]:
            disk = disks[interface]
            if (disk.get('size') != size or disk.get('datastore_id') != 'local-lvm'
                    or disk.get('path_in_datastore') != identity):
                raise ValueError('Worker disk identity differs: ' + interface)
        disks['scsi0']['size'] = 128
        if expected != change['after']:
            raise ValueError('Disk plan changes more than the authorized OS size')
        changed.append(WORKER)
    if changed != [WORKER]:
        raise ValueError('Expected exactly one worker OS disk resize')
    return changed
