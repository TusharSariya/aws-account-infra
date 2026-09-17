"""Read-only deployment gate: never drain or interrupt AI/CI to make room."""
import json


def verify(kubectl, run):
    def get(*args):
        return json.loads(run([kubectl, '--request-timeout=30s', *args, '-o', 'json']))
    pods = get('get', 'pods', '-A')['items']
    for pod in pods:
        labels = pod['metadata'].get('labels', {})
        if (pod.get('status', {}).get('phase') not in ('Succeeded', 'Failed') and
                ('kueue.x-k8s.io/queue-name' in labels or labels.get('app') == 'ai-runtime')):
            raise ValueError('Wait for active AI/CI work to finish; deployment never interrupts it')
    runtime = get('get', 'deployment', 'ai-runtime', '-n', 'homelab-models')
    if runtime['spec'].get('replicas', 1) != 0:
        raise ValueError('AI must be intentionally off before capacity rollout')
    queue = get('get', 'clusterqueue', 'homelab-compute')
    resources = queue['spec']['resourceGroups'][0]['flavors'][0]['resources']
    quotas = {r['name']: str(r['nominalQuota']) for r in resources}
    if quotas.get('cpu') not in ('31500m', '31.5') or quotas.get('memory') != '144Gi':
        raise ValueError('Apply the reviewed 31.5 CPU / 144 GiB queue reduction first')
    storage = get('get', 'storageclass', 'worker-local-retain')
    if storage['reclaimPolicy'] != 'Retain' or storage.get('allowVolumeExpansion', False):
        raise ValueError('Expected retained non-expandable worker local-path storage')
    # Existing restricted collector already mounts and verifies the worker data disk.
    code = """import json,os
p='/var/mnt/local-path-provisioner'
s=os.statvfs(p)
lines=open('/proc/self/mountinfo').read().splitlines()
ok=any(l.split()[4]==p and ' - xfs /dev/sdb1 ' in l for l in lines)
print(json.dumps({'mounted':ok,'free':s.f_bavail*s.f_frsize}))
"""
    disk = json.loads(run([kubectl, '-n', 'homelab-platform', 'exec', 'deployment/guest-capacity',
                          '--', 'python', '-c', code]))
    # 32 GiB data + 64 GiB scratch + 16 GiB operational headroom.
    if not disk['mounted'] or disk['free'] < 112 * 1024**3:
        raise ValueError('Worker data disk needs at least 112 GiB free and the expected XFS mount')
    return disk
