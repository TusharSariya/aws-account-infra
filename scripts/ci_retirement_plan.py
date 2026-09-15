"""Allow only retirement of the identified CI VM/image and exact worker RAM restoration."""
from copy import deepcopy
from ci_runner_plan import WORKER, RUNNER, IMAGE


def unknown(value):
    if isinstance(value, dict):
        return any(unknown(v) for v in value.values())
    if isinstance(value, list):
        return any(unknown(v) for v in value)
    return value is True


def guard(plan):
    if plan.get('errored') or plan.get('complete') is False or plan.get('deferred_changes'):
        raise ValueError('Complete successful plan required')
    changed = []
    for resource in plan.get('resource_changes', []):
        change = resource['change']
        if change['actions'] == ['no-op']:
            continue
        if resource.get('mode', 'managed') != 'managed':
            raise ValueError('Unexpected data change')
        address = resource['address']
        before, after = change.get('before'), change.get('after')
        if address == WORKER and change['actions'] == ['update']:
            expected = deepcopy(before)
            if (expected.get('vm_id') != 102 or expected.get('name') != 'talos-worker-01'
                    or expected.get('node_name') != 'pve'
                    or expected['memory'][0]['dedicated'] != 156 * 1024):
                raise ValueError('Worker identity or original RAM differs')
            expected['memory'][0]['dedicated'] = 172 * 1024
            if expected != after or unknown(change.get('after_unknown')):
                raise ValueError('Only exact worker RAM restoration is allowed')
        elif address == RUNNER and change['actions'] == ['delete']:
            if (after is not None or before.get('vm_id') != 103 or before.get('name') != 'ci-runner-01'
                    or before.get('node_name') != 'pve' or before.get('started') is not False
                    or before.get('on_boot') is not False
                    or len(before.get('network_device', [])) != 1
                    or before['network_device'][0]['mac_address'].lower() != '02:42:00:00:01:05'
                    or len(before.get('disk', [])) != 1 or before['disk'][0].get('size') != 100
                    or before['disk'][0].get('datastore_id') != 'local-lvm'):
                raise ValueError('Only the identified stopped CI VM may be deleted')
        elif address == IMAGE and change['actions'] == ['delete']:
            if (after is not None or before.get('node_name') != 'pve'
                    or before.get('datastore_id') != 'local'
                    or before.get('file_name') != 'ci-ubuntu-24.04-20260911.qcow2'
                    or before.get('checksum') != '612b2c0cc1bc413a6cb8c38fd611794caf0f2b436c50013d8b3794db12ad7354'):
                raise ValueError('Only the pinned CI image may be deleted')
        else:
            raise ValueError('Unexpected retirement change: ' + address)
        changed.append(address)
    if set(changed) != {WORKER, RUNNER, IMAGE}:
        raise ValueError('Retirement requires exactly VM, image and worker RAM restoration')
    return changed


def guard_ai_off(deployment, pods):
    metadata = deployment.get('metadata', {})
    if (metadata.get('namespace') != 'homelab-models' or metadata.get('name') != 'ai-runtime'
            or metadata.get('annotations', {}).get('homelab/desired-state') != 'off'
            or deployment.get('spec', {}).get('replicas') != 0 or pods.get('items') != []):
        raise ValueError('Retirement requires verified AI Off with no remaining AI Pods')
