"""Validate the shared pool against observed worker allocatable and Pod requests."""
from decimal import Decimal
import re


def quantity(value):
    match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)([a-zA-Z]*)', str(value))
    if not match:
        raise ValueError('Unsupported Kubernetes quantity: ' + str(value))
    number, unit = match.groups()
    scales = {'': 1, 'm': Decimal('.001'), 'Ki': 1024, 'Mi': 1024**2,
              'Gi': 1024**3, 'Ti': 1024**4, 'k': 1000, 'M': 1000**2, 'G': 1000**3}
    if unit not in scales:
        raise ValueError('Unsupported Kubernetes quantity suffix: ' + unit)
    return Decimal(number) * scales[unit]


def requests(pod, resource):
    spec = pod['spec']
    def requested(container):
        return quantity(container.get('resources', {}).get('requests', {}).get(resource, '0'))
    regular = sum((requested(c) for c in spec.get('containers', [])), Decimal(0))
    sidecars, peak = Decimal(0), Decimal(0)
    for container in spec.get('initContainers', []):
        amount = requested(container)
        if container.get('restartPolicy') == 'Always':
            sidecars += amount
            peak = max(peak, sidecars)
        else:
            peak = max(peak, sidecars + amount)
    return max(regular + sidecars, peak) + quantity(spec.get('overhead', {}).get(resource, '0'))


def verify(node, pods, reserve, pool=None):
    if pool is None:
        from pathlib import Path
        import yaml
        pool = yaml.safe_load((Path(__file__).resolve().parents[1] /
            "config/environments/kubernetes/homelab-ci/pool-values.yaml").read_text())
    if node['metadata']['name'] != 'talos-worker-01':
        raise ValueError('Expected talos-worker-01')
    if not any(c['type'] == 'Ready' and c['status'] == 'True' for c in node['status']['conditions']):
        raise ValueError('Worker must be Ready')
    # Use observed allocatable memory, including kernel/firmware reservations.
    # The reviewed pool plus platform reserve must fit after any VM resize.
    if quantity(node['status']['allocatable']['memory']) > quantity(node['status']['capacity']['memory']):
        raise ValueError('Node allocatable memory exceeds reported capacity')
    result = {}
    for resource in ('cpu', 'memory'):
        quota = pool[resource]
        observed = sum((requests(p, resource) for p in pods
                        if p['spec'].get('nodeName') == 'talos-worker-01'
                        and p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')
                        and 'kueue.x-k8s.io/queue-name' not in p['metadata'].get('labels', {})), Decimal(0))
        budget = quantity(reserve[resource])
        available = quantity(node['status']['allocatable'][resource])
        if observed > budget:
            raise ValueError(f'Platform {resource} requests {observed} exceed reviewed reserve {budget}')
        if quantity(quota) + budget > available:
            raise ValueError(f'Pool plus platform {resource} reserve exceeds node allocatable {available}')
        result[resource] = dict(allocatable=str(available), platform_observed=str(observed),
                                platform_reserved=str(budget), pool=quota)
    return result


def verify_storage(node, pods, summary, config, catalog):
    """Fail closed on missing/stale kubelet measurements; never use AI data disks."""
    from datetime import datetime, timezone
    if summary['node']['nodeName'] != node['metadata']['name']:
        raise ValueError('Storage sample belongs to another node')
    fs = summary['node']['fs']
    image_fs = summary['node']['runtime']['imageFs']
    for sample in [fs, image_fs]:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(sample['time'].replace('Z', '+00:00'))).total_seconds()
        if not 0 <= age <= 300:
            raise ValueError('Fresh root and image filesystem measurements required')
    pool = quantity(config['scratch'])
    headroom = quantity(config['storageHeadroom'])
    allocatable = quantity(node['status']['allocatable']['ephemeral-storage'])
    # Images share nodefs on Talos: root used already includes image storage.
    # Check both filesystems independently, also covering split imagefs.
    used = max(quantity(fs['usedBytes']), quantity(image_fs['usedBytes']))
    platform = sum((requests(p, 'ephemeral-storage') for p in pods
                    if p['spec'].get('nodeName') == node['metadata']['name']
                    and p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')
                    and 'kueue.x-k8s.io/queue-name' not in p['metadata'].get('labels', {})), Decimal(0))
    if (pool + max(used, platform) + headroom > allocatable
            or pool + headroom > min(quantity(fs['availableBytes']), quantity(image_fs['availableBytes']))):
        raise ValueError('Configured compute scratch plus measured platform/images and eviction headroom do not fit; review storage budget')
    live = sum(p['spec'].get('nodeName') == node['metadata']['name'] and
               p.get('status', {}).get('phase') not in ('Succeeded', 'Failed') for p in pods)
    # Upper bound across any mixture of catalog runners; allow ordinary Argo
    # and node services the explicitly reviewed additional Pod headroom.
    slots = min(int(quantity(config['cpu']) / min(quantity(c['cpu']) for c in catalog.values())),
                int(quantity(config['memory']) / min(c['memory'] * 1024**2 for c in catalog.values())),
                int(pool / min(c['scratch'] * 1024**2 for c in catalog.values())))
    if live + slots + config['podHeadroom'] > int(node['status']['allocatable']['pods']):
        raise ValueError('Insufficient Pod slots for catalog concurrency and platform headroom')
    return dict(pool=str(pool), measured_used_with_images=str(used), platform_requests=str(platform),
                headroom=str(headroom), allocatable=str(allocatable), projected_platform_pods=live,
                runner_slots=slots, pod_headroom=config['podHeadroom'])
