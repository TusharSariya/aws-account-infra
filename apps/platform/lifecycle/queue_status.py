"""Read-only Kueue status. A queue outage must never prevent lifecycle commands."""
from kube import Unavailable

PATH = '/apis/kueue.x-k8s.io/v1beta2/namespaces/homelab-models/workloads'
VISIBILITY = '/apis/visibility.kueue.x-k8s.io/v1beta2/clusterqueues/homelab-compute/pendingworkloads'
NAMESPACES = {'homelab-models', 'homelab-jobs', 'arc-runners'}


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
         'requested': {'cpu': '35.75', 'memory': '77Gi'},
         'reserved': w.get('status', {}).get('admission', {}).get('podSetAssignments', []),
         'conditions': [{'type': c['type'], 'status': c['status'], 'reason': c.get('reason', ''),
                         'message': c.get('message', '')} for c in w.get('status', {}).get('conditions', [])]}
        for w in owned]}


def observe(api, pods):
    try:
        return summarize(api.call('GET', PATH)['items'], pods, api.call('GET', VISIBILITY)['items'])
    except (Unavailable, KeyError, TypeError):
        return {'queue': 'ai', 'cluster_queue': 'homelab-compute', 'unavailable': True,
                'reason': 'Queue status unavailable; lifecycle controls remain available', 'workloads': []}
