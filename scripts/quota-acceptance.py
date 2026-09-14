#!/usr/bin/env python3
"""Explicit CI quota proof in two stages around separately approved maintenance."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/platform/storage'))
from collector import healthy_sample
from quota_proof import require_proof, template_revision
from workload_state import is_terminated

NAMESPACE = 'homelab-platform'
RECORD = 'quota-live-acceptance'


def main(phase):
    if (phase not in ('prepare', 'verify') or os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('QUOTA_ACCEPTANCE_CONFIRM') != 'verify-disposable-quotas-and-reboot'):
        raise ValueError('Explicit reviewed-main quota maintenance required')
    kubectl = os.environ['KUBECTL']

    def run(args, value=None):
        result = subprocess.run([kubectl, '--request-timeout=30s', *args],
            input=None if value is None else json.dumps(value), capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise ValueError('Quota acceptance API request failed')
        return json.loads(result.stdout) if result.stdout.strip() else None

    def get(resource, name, namespace=NAMESPACE, optional=False):
        return run(['get', resource, name, '-o', 'json', *(['-n', namespace] if namespace else []),
                    *(['--ignore-not-found'] if optional else [])])

    templates = {mode: get('configmap', 'quota-' + mode + '-template')['data']['job.yaml']
                 for mode in ('admin', 'consumer')}
    revision = template_revision(templates)
    config = yaml.safe_load((ROOT / 'config/environments/kubernetes/homelab/capacity-values.yaml').read_text())
    if config['enabled'] is not True:
        raise ValueError('Collectors must be enabled before maintenance proof')
    for mode in ('guest', 'physical'):
        sample = json.loads(get('configmap', mode + '-capacity')['data']['sample.json'])
        if (not healthy_sample(mode, config['config'], sample, time.time())
                or any(value['used_percent'] >= 80 for value in sample.values())):
            raise ValueError('Fresh healthy capacity below warning required')
    node = get('node', 'talos-worker-01', namespace=None)
    for name in ('ollama', 'odysseus', 'chromadb', 'searxng', 'ai-runtime'):
        deployment = get('deployment', name, namespace='homelab-models', optional=name == 'ai-runtime')
        if deployment and deployment['spec'].get('replicas', 1) != 0:
            raise ValueError('AI must remain intentionally off during quota maintenance')
    pods = run(['get', 'pods', '-n', 'homelab-models', '-o', 'json'])['items']
    if any(not is_terminated(pod) for pod in pods):
        raise ValueError('AI still has active or unverified Pods')
    current = get('configmap', RECORD, optional=True)
    old = json.loads(current['data']['proof.json']) if current else None
    if phase == 'prepare':
        if old and old.get('phase') != 'completed':
            raise ValueError('Previous quota proof requires explicit recovery')
        record = {'run_id': uuid.uuid4().hex, 'phase': 'preparing', 'revision': revision,
                  'filesystem': config['config']['filesystemUUID'], 'node_uid': node['metadata']['uid'],
                  'boot_before': node['status']['nodeInfo']['bootID'], 'started_at': time.time(),
                  'source_commit': os.environ['GITHUB_SHA']}
    else:
        record = old or {}
        if (record.get('phase') != 'prepared' or record.get('revision') != revision
                or record.get('filesystem') != config['config']['filesystemUUID']
                or record.get('node_uid') != node['metadata']['uid']
                or record.get('boot_before') == node['status']['nodeInfo']['bootID']
                or not 0 <= time.time() - record.get('started_at', 0) <= 86400):
            raise ValueError('Expected prepared fixtures and an observed worker reboot')

    def verify_boot():
        observed = get('node', 'talos-worker-01', namespace=None)
        if (observed['metadata']['uid'] != node['metadata']['uid']
                or observed['status']['nodeInfo']['bootID'] != node['status']['nodeInfo']['bootID']
                or not any(c.get('type') == 'Ready' and c.get('status') == 'True'
                           for c in observed['status'].get('conditions', []))):
            raise ValueError('Worker identity, boot or readiness changed during quota proof')
        return observed

    def save():
        nonlocal current
        value = {'apiVersion': 'v1', 'kind': 'ConfigMap',
                 'metadata': {'name': RECORD, 'namespace': NAMESPACE},
                 'data': {'proof.json': json.dumps(record, sort_keys=True)}}
        path = '/api/v1/namespaces/' + NAMESPACE + '/configmaps'
        if current:
            value['metadata'] = current['metadata']
            current = run(['replace', '--raw=' + path + '/' + RECORD + '?fieldValidation=Strict', '-f', '-'], value)
        else:
            current = run(['create', '--raw=' + path + '?fieldValidation=Strict', '-f', '-'], value)

    def job(mode, operation):
        verify_boot()
        value = yaml.safe_load(templates[mode])
        if (value['kind'] != 'Job' or value['metadata']['namespace'] != NAMESPACE
                or value['spec']['template']['spec']['containers'][0]['command'] != ['python', '-B', '/code/live_quota.py']):
            raise ValueError('Unexpected approved quota Job template')
        name = 'quota-' + mode + '-' + operation + '-' + phase[0] + '-' + record['run_id']
        value['metadata']['name'] = name
        evidence = {'homelab/proof-revision': revision, 'homelab/proof-boot-id': node['status']['nodeInfo']['bootID']}
        value['metadata'].setdefault('annotations', {}).update(evidence)
        value['spec']['template']['spec']['containers'][0]['args'] = [operation, record['run_id']]
        existing = get('job', name, optional=True)
        if existing:
            if any(existing['metadata'].get('annotations', {}).get(key) != expected for key, expected in evidence.items()):
                raise ValueError('Existing proof Job does not match the current boot and reviewed template')
        else:
            run(['create', '--raw=/apis/batch/v1/namespaces/' + NAMESPACE + '/jobs?fieldValidation=Strict', '-f', '-'], value)
        deadline = time.monotonic() + 210
        while time.monotonic() < deadline:
            status = get('job', name).get('status', {})
            if status.get('failed'):
                raise ValueError('Quota ' + mode + '/' + operation + ' Job failed')
            if status.get('succeeded') == 1:
                verify_boot()
                print('PASS: quota ' + mode + '/' + operation + ' Job completed', flush=True)
                return
            time.sleep(3)
        raise ValueError('Quota ' + mode + '/' + operation + ' Job did not complete')

    if phase == 'prepare':
        save()
        job('admin', 'prepare')
        job('consumer', 'consumer')
        job('admin', 'verify')
        verify_boot()
        record['phase'] = 'prepared'
        save()
        print('PASS: disposable quota and actual Pod user-namespace proof before maintenance')
    else:
        job('consumer', 'consumer')
        job('admin', 'verify')
        job('admin', 'cleanup')
        node = verify_boot()
        record.update(phase='completed', completed_at=time.time(), boot_after=node['status']['nodeInfo']['bootID'])
        save()
        require_proof(record, revision, config['config']['filesystemUUID'], node, time.time())
        print('PASS: live hard-limit enforcement, neighboring writes, user namespace and data/quota persistence across worker reboot')


if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except Exception as error:
        print(str(error) if isinstance(error, ValueError) else 'Quota maintenance failed; inspect retained fixtures and Jobs', file=sys.stderr)
        sys.exit(1)
