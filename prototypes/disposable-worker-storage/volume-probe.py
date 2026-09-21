#!/usr/bin/env python3
"""Throwaway marker probe; never deletes a VM, PVC, PV or backend volume.

Run on the laptop. create mounts a retained scratch PVC on a named test worker.
release removes only its probe Pod; verify mounts the SAME claim on a new worker.
VM lifecycle operations remain separate until installed PVE/CSI ownership is checked.
"""
import argparse
import json
from pathlib import Path
import secrets
import subprocess

NS = 'prototype-worker-storage'
CLAIM = 'retained-marker'
POD = 'marker-probe'

def run(cmd):
    return subprocess.check_output(cmd, timeout=180)

def resources(node, storage_class):
    return [
        {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NS,
          'labels': {'pod-security.kubernetes.io/enforce': 'restricted'}}},
        {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': CLAIM, 'namespace': NS},
         'spec': {'accessModes': ['ReadWriteOnce'], 'storageClassName': storage_class,
                  'resources': {'requests': {'storage': '1Gi'}}}},
        {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': POD, 'namespace': NS},
         'spec': {'automountServiceAccountToken': False,
                  'nodeSelector': {'kubernetes.io/hostname': node},
                  'securityContext': {'runAsNonRoot': True, 'runAsUser': 1000,
                                      'runAsGroup': 1000, 'fsGroup': 1000,
                                      'seccompProfile': {'type': 'RuntimeDefault'}},
                  'containers': [{'name': 'probe',
                    'image': 'docker.io/library/busybox:1.37.0@sha256:9db7b59979c38555a39def84a31fb98b5296952f9e3afd4f6f11f05b07adfab0',
                    'command': ['sleep', '86400'],
                    'securityContext': {'readOnlyRootFilesystem': True, 'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}},
                    'resources': {'requests': {'cpu': '10m', 'memory': '16Mi'}, 'limits': {'memory': '64Mi'}},
                    'volumeMounts': [{'name': 'data', 'mountPath': '/data'}]}],
                  'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': CLAIM}}]}}
    ]

def main():
    global NS
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['render', 'create', 'release', 'verify'])
    p.add_argument('--namespace', default=NS)
    p.add_argument('--node', required=True)
    p.add_argument('--storage-class', required=True)
    p.add_argument('--kubectl', default='./kubectl')
    p.add_argument('--kubeconfig', default='private/kubeconfig')
    p.add_argument('--evidence', type=Path, default=Path('private/storage-probe.json'))
    a = p.parse_args()
    NS = a.namespace
    docs = resources(a.node, a.storage_class)
    if a.action == 'render':
        print(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': docs}, indent=2))
        return
    k = [a.kubectl, '--kubeconfig', a.kubeconfig, '--request-timeout=15s']
    config = json.loads(run(k + ['config', 'view', '--minify', '-o', 'json']))
    cluster = config['clusters'][0]
    if cluster['name'] != 'laptop-wifi-PROTOTYPE' or cluster['cluster']['server'] != 'https://10.0.2.15:6443':
        raise SystemExit('Refusing a context other than the isolated laptop prototype')
    sc = json.loads(run(k + ['get', 'storageclass', a.storage_class, '-o', 'json']))
    if sc.get('provisioner') != 'csi.proxmox.sinextra.dev' or sc.get('reclaimPolicy') != 'Retain':
        raise SystemExit('Requires verified Proxmox CSI storage class with Retain policy')
    evidence = None
    if a.action != 'create':
        evidence = json.loads(a.evidence.read_text())
        claim = json.loads(run(k + ['-n', NS, 'get', 'pvc', CLAIM, '-o', 'json']))
        if claim['metadata']['uid'] != evidence['claim_uid'] or claim['spec']['volumeName'] != evidence['pv']:
            raise SystemExit('Claim/volume identity changed; refusing the test')
        pv = json.loads(run(k + ['get', 'pv', evidence['pv'], '-o', 'json']))
        if pv['metadata']['uid'] != evidence['pv_uid'] or pv['spec']['csi']['volumeHandle'] != evidence['volume_handle']:
            raise SystemExit('Backend volume identity changed; refusing the test')
    if a.action == 'release':
        run(k + ['-n', NS, 'delete', 'pod', POD, '--wait=true', '--timeout=120s'])
        attachments = json.loads(run(k + ['get', 'volumeattachments', '-o', 'json']))['items']
        refs = [x['metadata']['name'] for x in attachments if x['spec'].get('source', {}).get('persistentVolumeName') == evidence['pv']]
        print(json.dumps({'remaining_volumeattachments': refs,
                          'next': 'Wait for detach and inspect PVE disk references before any VM deletion.'}, indent=2))
        return
    if a.action == 'create':
        if a.evidence.exists():
            raise SystemExit('Evidence already exists; do not overwrite a prior marker')
        old = run(k + ['get', 'namespace', NS, '--ignore-not-found', '-o', 'name']).strip()
        if old:
            raise SystemExit('Probe namespace already exists; inspect it before creating anything')
    elif a.node == evidence['node']:
        raise SystemExit('Verify requires a replacement node identity')
    # Verification creates only the new Pod; the original PVC must already exist.
    selected = docs if a.action == 'create' else [docs[-1]]
    subprocess.run(k + ['apply', '-f', '-'], input=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': selected}).encode(), check=True, timeout=60)
    run(k + ['-n', NS, 'wait', '--for=condition=Ready', 'pod/' + POD, '--timeout=120s'])
    if a.action == 'create':
        marker = 'prototype-' + secrets.token_hex(16)
        run(k + ['-n', NS, 'exec', POD, '--', 'sh', '-ec', 'test ! -e /data/marker; printf "%s\\n" "$1" > /data/marker; sync', 'sh', marker])
        claim = json.loads(run(k + ['-n', NS, 'get', 'pvc', CLAIM, '-o', 'json']))
        pv = json.loads(run(k + ['get', 'pv', claim['spec']['volumeName'], '-o', 'json']))
        evidence = {'node': a.node, 'marker': marker, 'claim_uid': claim['metadata']['uid'],
                    'pv': pv['metadata']['name'], 'pv_uid': pv['metadata']['uid'],
                    'volume_handle': pv['spec']['csi']['volumeHandle']}
        a.evidence.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with a.evidence.open('x') as f:
            json.dump(evidence, f, indent=2)
        a.evidence.chmod(0o600)
    actual = run(k + ['-n', NS, 'exec', POD, '--', 'cat', '/data/marker']).decode().strip()
    if actual != evidence['marker']:
        raise SystemExit('Marker mismatch')
    print(json.dumps({'result': 'marker verified', 'node': a.node, 'pv': evidence['pv'],
                      'replacement': a.action == 'verify'}, indent=2))

if __name__ == '__main__':
    main()
