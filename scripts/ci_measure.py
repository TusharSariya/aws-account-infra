"""Create, use and remove an isolated temporary Pod storage observer.

The observer has no Kubernetes token or network access. Read-only host mounts
exist only in this administration fixture, never in an ARC runner. Every start
checks the existing platform reserve and node storage guard. This tool does not
adopt budgets or claim complete sampling coverage.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import uuid

import yaml
from kueue_capacity import verify, verify_storage

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = 'homelab-platform'
IMAGE = 'python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6'
HOST_PATHS = ['/proc', '/sys/fs/cgroup', '/var/lib/kubelet/pods', '/var/log/pods',
              '/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots',
              '/var/lib/containerd/io.containerd.content.v1.content/blobs/sha256']


def run(kube, args, value=None):
    return subprocess.check_output([*kube, *args], input=None if value is None else json.dumps(value).encode())


def resource(kind, name):
    return {'apiVersion': 'v1', 'kind': kind, 'metadata': {
        'name': name, 'namespace': NAMESPACE, 'labels': {'homelab/ci-measurement': name}}}


def observer(name):
    pod = resource('Pod', name)
    pod['spec'] = {
        'automountServiceAccountToken': False, 'restartPolicy': 'Never',
        'activeDeadlineSeconds': 21600,
        'nodeName': 'talos-worker-01',
        'securityContext': {'seccompProfile': {'type': 'RuntimeDefault'}},
        'containers': [{'name': 'observer', 'image': IMAGE,
            'command': ['python', '-B', '-c', 'import time; time.sleep(21600)'],
            'securityContext': {'runAsUser': 0, 'allowPrivilegeEscalation': False,
                'readOnlyRootFilesystem': True,
                'capabilities': {'drop': ['ALL'], 'add': ['DAC_READ_SEARCH', 'SYS_PTRACE']}},
            'resources': {'requests': {'cpu': '100m', 'memory': '128Mi', 'ephemeral-storage': '16Mi'},
                          'limits': {'cpu': '250m', 'memory': '256Mi', 'ephemeral-storage': '64Mi'}},
            'volumeMounts': [{'name': 'code', 'mountPath': '/code', 'readOnly': True}] + [
                {'name': 'host-' + str(i), 'mountPath': '/host' + path, 'readOnly': True}
                for i, path in enumerate(HOST_PATHS)]}],
        'volumes': [{'name': 'code', 'configMap': {'name': name}}] + [
            {'name': 'host-' + str(i), 'hostPath': {'path': path, 'type': 'Directory'}}
            for i, path in enumerate(HOST_PATHS)]}
    return pod


def private(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError('Private directory owned by this user with mode 0700 required')
    return path


def cleanup(kube, record):
    for kind in ('Pod', 'ConfigMap'):
        if kind not in record['uids']:
            continue
        current = json.loads(run(kube, ['get', kind, record['name'], '-n', NAMESPACE,
                                        '--ignore-not-found', '-o', 'json']) or b'null')
        if current is None:
            continue
        if (current['metadata']['uid'] != record['uids'][kind] or
                current['metadata'].get('labels', {}).get('homelab/ci-measurement') != record['name']):
            raise ValueError('Observer identity changed; refusing deletion')
        run(kube, ['delete', kind, record['name'], '-n', NAMESPACE, '--wait=true', '--timeout=60s'])


def start(kube, directory):
    receipt = directory / 'observer.json'
    if receipt.exists():
        raise ValueError('Existing observer receipt; stop it or use a fresh private directory')
    name = 'ci-measure-' + uuid.uuid4().hex[:12]
    pod = observer(name)
    config = yaml.safe_load((ROOT / 'config/environments/kubernetes/homelab-ci/pool-values.yaml').read_text())
    node = json.loads(run(kube, ['get', 'node', config['worker'], '-o', 'json']))
    pods = json.loads(run(kube, ['get', 'pods', '-A', '-o', 'json']))['items'] + [pod]
    report = verify(node, pods, config['platformReserve'], config)
    summary = json.loads(run(kube, ['get', '--raw=/api/v1/nodes/' + config['worker'] + '/proxy/stats/summary']))
    catalog = json.loads((ROOT / 'config/environments/kubernetes/homelab-ci/runner-catalog.json').read_text())
    report['storage'] = verify_storage(node, pods, summary, config, catalog)
    code = resource('ConfigMap', name)
    code['data'] = {'ci_pod_usage.py': (ROOT / 'scripts/ci_pod_usage.py').read_text()}
    record = {'name': name, 'uids': {}, 'capacity': report}
    try:
        for value in (code, pod):
            # Initial OpenAPI discovery is much larger than ordinary reads over
            # the private relay. Keep validation enabled with a bounded timeout.
            created = json.loads(run(kube, ['create', '--request-timeout=120s', '-f', '-', '-o', 'json'], value))
            record['uids'][value['kind']] = created['metadata']['uid']
            receipt.write_text(json.dumps(record, indent=2) + '\n')
            receipt.chmod(0o600)
        run(kube, ['wait', 'pod/' + name, '-n', NAMESPACE, '--for=condition=Ready', '--timeout=120s'])
    except Exception:
        # Preserve receipt if cleanup needs a later recovery attempt.
        cleanup(kube, record)
        raise
    print('Observer ready:', name)


def capture(kube, directory, runner):
    record = json.loads((directory / 'observer.json').read_text())
    pod = json.loads(run(kube, ['get', 'pod', runner, '-n', 'arc-runners', '-o', 'json']))
    if pod['spec'].get('nodeName') != 'talos-worker-01':
        raise ValueError('Runner must be assigned to the reviewed worker')
    statuses = [*pod['status'].get('containerStatuses', []), *pod['status'].get('initContainerStatuses', [])]
    images = {entry['imageID'].split('@')[-1] for entry in statuses if entry.get('imageID')}
    # The runtime's sandbox image is charged alongside all declared containers.
    node = json.loads(run(kube, ['get', 'node', 'talos-worker-01', '-o', 'json']))
    for entry in node['status'].get('images', []):
        if 'registry.k8s.io/pause:3.10.1' in entry['names']:
            images.update(name.split('@')[-1] for name in entry['names'] if '@sha256:' in name)
    if not images:
        raise ValueError('Observed immutable image identities required')
    args = ['exec', record['name'], '-n', NAMESPACE, '-c', 'observer', '--',
            'python', '-B', '/code/ci_pod_usage.py', '--uid', pod['metadata']['uid'], '--name', runner]
    for image in sorted(images):
        args += ['--image', image]
    sample = json.loads(run(kube, args))
    sample['images'] = sorted(images)
    sample['containers'] = [{
        **{key: entry.get(key) for key in ('name', 'containerID', 'imageID')},
        'state': {state: {key: value[key] for key in ('startedAt', 'finishedAt', 'exitCode', 'reason') if key in value}
                  for state, value in entry.get('state', {}).items()}}
        for entry in statuses]
    destination = directory / (pod['metadata']['uid'] + '.jsonl')
    with destination.open('a') as output:
        output.write(json.dumps(sample) + '\n')
    destination.chmod(0o600)
    print(json.dumps({key: sample[key] for key in ('pod_uid', 'allocated_bytes', 'memory_peak_bytes', 'failures')}))


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'sample', 'stop'])
    parser.add_argument('--private', type=Path, required=True)
    parser.add_argument('--kubeconfig', type=Path, required=True)
    parser.add_argument('--runner')
    args = parser.parse_args()
    directory = private(args.private)
    kube = ['kubectl', '--request-timeout=15s', '--kubeconfig', str(args.kubeconfig)]
    if args.action == 'start':
        start(kube, directory)
    elif args.action == 'sample':
        if not args.runner:
            parser.error('--runner required for sample')
        capture(kube, directory, args.runner)
    else:
        cleanup(kube, json.loads((directory / 'observer.json').read_text()))
        print('Owned observer Pod and ConfigMap removed')
