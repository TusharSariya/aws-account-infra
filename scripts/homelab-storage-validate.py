#!/usr/bin/env python3
"""Verify worker PVC placement, persistence, retention and request quotas using disposable fixtures."""
import json
import os
import subprocess
import time
import uuid

K = os.environ.get('KUBECTL', 'kubectl')
TC = os.environ.get('TALOSCTL', 'talosctl')
IMAGE = 'docker.io/library/busybox:1.37.0@sha256:9db7b59979c38555a39def84a31fb98b5296952f9e3afd4f6f11f05b07adfab0'


def run(args, value=None, check=True):
    p = subprocess.run(args, input=json.dumps(value) if value else None,
                       text=True, capture_output=True, timeout=180)
    if check and p.returncode:
        raise RuntimeError('Storage acceptance command failed: ' + args[0])
    return p


def get(kind, name, namespace=None):
    return json.loads(run([K, 'get', kind, name, '-o', 'json'] + (['-n', namespace] if namespace else [])).stdout)


def create(value):
    return run([K, 'create', '-f', '-'], value)


def main():
    for suffix, policy in [('retain', 'Retain'), ('delete', 'Delete')]:
        sc = get('storageclass', 'worker-local-' + suffix)
        assert sc['provisioner'] == 'rancher.io/local-path'
        assert sc['reclaimPolicy'] == policy and sc['volumeBindingMode'] == 'WaitForFirstConsumer'
        assert sc['allowedTopologies'] == [{'matchLabelExpressions': [
            {'key': 'kubernetes.io/hostname', 'values': ['talos-worker-01']}]}]
    for name, size in [('homelab-models', '800Gi'), ('homelab-services', '100Gi'), ('homelab-data', '100Gi')]:
        assert get('resourcequota', 'storage-budget', name)['spec']['hard'] == {
            'requests.storage': size, 'persistentvolumeclaims': '10'}
        assert get('limitrange', 'storage-claim-size', name)['spec']['limits'] == [
            {'type': 'PersistentVolumeClaim', 'min': {'storage': '1Gi'}, 'max': {'storage': size}}]
    ns = 'storage-check-' + uuid.uuid4().hex[:10]
    fixtures = []
    claim_uids = set()
    create({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': ns, 'labels': {
        'pod-security.kubernetes.io/enforce': 'restricted', 'pod-security.kubernetes.io/enforce-version': 'v1.36'}}})
    def pvc(name, suffix):
        return {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': name, 'namespace': ns},
                'spec': {'accessModes': ['ReadWriteOnce'], 'storageClassName': 'worker-local-' + suffix,
                         'resources': {'requests': {'storage': '1Gi'}}}}
    def pod(name):
        return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': ns}, 'spec': {
            'automountServiceAccountToken': False,
            'nodeSelector': {'kubernetes.io/hostname': 'talos-worker-01'},
            'securityContext': {'runAsNonRoot': True, 'runAsUser': 1000, 'runAsGroup': 1000,
                                'seccompProfile': {'type': 'RuntimeDefault'}},
            'containers': [{'name': 'test', 'image': IMAGE, 'command': ['sleep', '600'],
                'securityContext': {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}},
                'resources': {'requests': {'cpu': '10m', 'memory': '16Mi'}, 'limits': {'cpu': '100m', 'memory': '32Mi'}},
                'volumeMounts': [{'name': 'data', 'mountPath': '/data'}]}],
            'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': name}}]}}
    def ready(name):
        run([K, 'wait', '-n', ns, 'pod/' + name, '--for=condition=Ready', '--timeout=120s'])
    try:
        create({'apiVersion': 'v1', 'kind': 'ResourceQuota', 'metadata': {'name': 'test-budget', 'namespace': ns},
                'spec': {'hard': {'requests.storage': '2Gi', 'persistentvolumeclaims': '2'}}})
        for suffix in ['retain', 'delete']:
            create(pvc(suffix, suffix))
            claim_uids.add(get('pvc', suffix, ns)['metadata']['uid'])
        denied = run([K, 'create', '--dry-run=server', '-f', '-'], pvc('over-budget', 'delete'), check=False)
        assert denied.returncode != 0 and 'exceeded quota' in denied.stderr
        print('PASS: requested-capacity/count quota rejects excess PVC')
        for suffix in ['retain', 'delete']:
            claim = get('pvc', suffix, ns)
            assert claim['status']['phase'] == 'Pending', 'PVC must wait for its consumer'
            create(pod(suffix))
            ready(suffix)
            claim = get('pvc', suffix, ns)
            pv = get('pv', claim['spec']['volumeName'])
            assert pv['spec']['claimRef']['uid'] == claim['metadata']['uid']
            fixtures.append((pv['metadata']['name'], claim['metadata']['uid']))
            path = pv['spec']['hostPath']['path']
            assert path.startswith('/var/mnt/local-path-provisioner/pvc-' + claim['metadata']['uid'] + '_')
            affinity = pv['spec']['nodeAffinity']['required']['nodeSelectorTerms']
            assert affinity == [{'matchExpressions': [
                {'key': 'kubernetes.io/hostname', 'operator': 'In', 'values': ['talos-worker-01']}]}]
            proof = uuid.uuid4().hex
            run([K, 'exec', '-n', ns, suffix, '--', 'sh', '-c', 'printf %s "$1" > /data/proof; sync', 'sh', proof])
            run([K, 'delete', 'pod', suffix, '-n', ns, '--wait=true'])
            create(pod(suffix))
            ready(suffix)
            assert run([K, 'exec', '-n', ns, suffix, '--', 'cat', '/data/proof']).stdout == proof
            run([K, 'delete', 'pod', suffix, '-n', ns, '--wait=true'])
            run([K, 'delete', 'pvc', suffix, '-n', ns, '--wait=true'])
            if suffix == 'retain':
                for _ in range(30):
                    if get('pv', pv['metadata']['name'])['status']['phase'] == 'Released':
                        break
                    time.sleep(2)
                else:
                    raise RuntimeError('Retain PV did not enter Released phase')
                assert run([TC, '-n', '10.42.0.222', 'read', path + '/proof']).stdout == proof
            else:
                run([K, 'wait', '--for=delete', 'pv/' + pv['metadata']['name'], '--timeout=120s'])
            print('PASS: ' + suffix + ' PVC worker placement, pod-recreation persistence and reclaim behavior')
    finally:
        # Include volumes that bound before a pod-readiness failure.
        all_pvs = json.loads(run([K, 'get', 'pv', '-o', 'json']).stdout)['items']
        fixtures = [(pv['metadata']['name'], pv['spec']['claimRef']['uid']) for pv in all_pvs
                    if pv['spec'].get('claimRef', {}).get('uid') in claim_uids
                    and pv['spec']['claimRef'].get('namespace') == ns]
        # Only change reclaim policy for PVs verified against our newly created claim UIDs.
        for name, uid in fixtures:
            result = run([K, 'get', 'pv', name, '-o', 'json', '--ignore-not-found'], check=False)
            if result.returncode == 0 and result.stdout.strip():
                pv = json.loads(result.stdout)
                if pv['spec']['claimRef']['uid'] != uid or pv['spec']['claimRef']['namespace'] != ns:
                    raise RuntimeError('Refusing cleanup of a foreign PV')
                run([K, 'patch', 'pv', name, '--type=merge', '-p', '{"spec":{"persistentVolumeReclaimPolicy":"Delete"}}'])
        run([K, 'delete', 'namespace', ns, '--wait=true', '--timeout=120s'])
        for name, _ in fixtures:
            run([K, 'wait', '--for=delete', 'pv/' + name, '--timeout=120s'])
    print('PASS: disposable storage fixtures removed; application namespaces and retained data untouched')


if __name__ == '__main__':
    main()
