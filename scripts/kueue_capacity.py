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


def verify(node, pods, reserve):
    if node['metadata']['name'] != 'talos-worker-01':
        raise ValueError('Expected talos-worker-01')
    if not any(c['type'] == 'Ready' and c['status'] == 'True' for c in node['status']['conditions']):
        raise ValueError('Worker must be Ready')
    # The 172-GiB guest exposes 168.92 GiB after kernel/firmware reservations.
    # The allocatable check below remains the admission budget authority.
    if quantity(node['status']['capacity']['memory']) < 168 * 1024**3:
        raise ValueError('Restore worker to 172 GiB before enabling the pool')
    result = {}
    for resource, pool in [('cpu', '36'), ('memory', '160Gi')]:
        observed = sum((requests(p, resource) for p in pods
                        if p['spec'].get('nodeName') == 'talos-worker-01'
                        and p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')
                        and 'kueue.x-k8s.io/queue-name' not in p['metadata'].get('labels', {})), Decimal(0))
        budget = quantity(reserve[resource])
        available = quantity(node['status']['allocatable'][resource])
        if observed > budget:
            raise ValueError(f'Platform {resource} requests {observed} exceed reviewed reserve {budget}')
        if quantity(pool) + budget > available:
            raise ValueError(f'Pool plus platform {resource} reserve exceeds node allocatable {available}')
        result[resource] = dict(allocatable=str(available), platform_observed=str(observed),
                                platform_reserved=str(budget), pool=pool)
    return result
