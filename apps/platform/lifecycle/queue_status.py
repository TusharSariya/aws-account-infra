"""Read-only Kueue status. A queue outage must never prevent lifecycle commands."""
from kube import Unavailable

PATH = '/apis/kueue.x-k8s.io/v1beta2/namespaces/homelab-models/workloads'
VISIBILITY = '/apis/visibility.kueue.x-k8s.io/v1beta2/clusterqueues/homelab-compute/pendingworkloads'
NAMESPACES = {'homelab-models', 'homelab-jobs', 'arc-runners'}


def requested(workload):
    """Report actual PodSet requests, including initialization peaks and overhead."""
    from decimal import Decimal
    import re
    def quantity(value):
        match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)(m|Ki|Mi|Gi|Ti|k|M|G)?', str(value))
        if not match:
            raise ValueError('Unsupported resource quantity')
        scales = {'': 1, 'm': Decimal('.001'), 'Ki': 1024, 'Mi': 1024**2,
                  'Gi': 1024**3, 'Ti': 1024**4, 'k': 1000, 'M': 1000**2, 'G': 1000**3}
        return Decimal(match[1]) * scales[match[2] or '']
    totals = {'cpu': Decimal(0), 'memory': Decimal(0)}
    for item in workload.get('spec', {}).get('podSets', []):
        spec = item['template']['spec']
        for resource in totals:
            def amount(container):
                return quantity(container.get('resources', {}).get('requests', {}).get(resource, 0))
            regular = sum((amount(c) for c in spec.get('containers', [])), Decimal(0))
            sidecars, peak = Decimal(0), Decimal(0)
            for container in spec.get('initContainers', []):
                value = amount(container)
                if container.get('restartPolicy') == 'Always':
                    sidecars += value
                    peak = max(peak, sidecars)
                else:
                    peak = max(peak, sidecars + value)
            totals[resource] += item['count'] * (max(regular + sidecars, peak) +
                quantity(spec.get('overhead', {}).get(resource, 0)))
    return {'cpu': format(totals['cpu'], 'f'),
            'memory': format(totals['memory'] / 1024**3, 'f') + 'Gi'}


def summarize(workloads, pods, visibility):
    ordered = sorted((w for w in workloads if w['metadata']['namespace'] in NAMESPACES and
        not any(c['type'] == 'Finished' and c['status'] == 'True' for c in w.get('status', {}).get('conditions', []))),
        key=lambda w: (w['metadata'].get('creationTimestamp', ''), w['metadata']['name']))
    pending = {(w['metadata']['namespace'], w['metadata']['name']): w['positionInClusterQueue'] + 1 for w in visibility}
    uids = {pod['metadata']['uid'] for pod in pods}
    owned = [w for w in ordered if any(o.get('uid') in uids for o in w['metadata'].get('ownerReferences', []))]
    return {'queue': 'ai', 'cluster_queue': 'homelab-compute', 'pending_count': len(pending), 'workloads': [
        {'name': w['metadata']['name'], 'created_at': w['metadata'].get('creationTimestamp'),
         'waiting_position': pending.get((w['metadata']['namespace'], w['metadata']['name'])),
         'requested': requested(w),
         'reserved': w.get('status', {}).get('admission', {}).get('podSetAssignments', []),
         'conditions': [{'type': c['type'], 'status': c['status'], 'reason': c.get('reason', ''),
                         'message': c.get('message', '')} for c in w.get('status', {}).get('conditions', [])]}
        for w in owned]}


def observe(api, pods):
    try:
        return summarize(api.call('GET', PATH)['items'], pods, api.call('GET', VISIBILITY)['items'])
    except (Unavailable, KeyError, TypeError, ValueError):
        return {'queue': 'ai', 'cluster_queue': 'homelab-compute', 'unavailable': True,
                'reason': 'Queue status unavailable; lifecycle controls remain available', 'workloads': []}
