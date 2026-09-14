#!/usr/bin/env python3
"""Explicit reviewed CI reset. Routine apply never invokes this entry point."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'apps/platform/storage'), str(ROOT / 'apps/platform/migration')]
from collector import healthy_sample
from reset import CLAIMS, validate_receipt
from quota_proof import require_proof, template_revision
from workload_state import is_terminated


def main():
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REF') != 'refs/heads/main' or
            os.environ.get('AI_RESET_CONFIRM') != 'reset-three-ai-volumes-v1'):
        raise ValueError('Explicit reviewed main reset required')
    kubectl = os.environ['KUBECTL']
    def run(args, value=None):
        result = subprocess.run([kubectl, '--request-timeout=30s', *args], input=None if value is None else json.dumps(value),
                                capture_output=True, text=True, timeout=700)
        if result.returncode:
            raise ValueError('Migration API operation failed; private output suppressed')
        return json.loads(result.stdout) if result.stdout.strip().startswith('{') else result.stdout
    def get(resource, name, namespace=None):
        return run(['get', resource, name, '-o', 'json', *(['-n', namespace] if namespace else [])])
    values = yaml.safe_load((ROOT / 'config/environments/kubernetes/homelab/capacity-values.yaml').read_text())
    if values['enabled'] is not True:
        raise ValueError('Continuous quota/capacity reconciliation must be enabled before migration')
    for mode in ('guest', 'physical'):
        sample = json.loads(get('configmap', mode + '-capacity', 'homelab-platform')['data']['sample.json'])
        if not healthy_sample(mode, values['config'], sample, time.time()) or any(v['used_percent'] >= 80 for v in sample.values()):
            raise ValueError('Fresh healthy capacity below warning thresholds required')
    for name in ('ollama', 'odysseus', 'chromadb', 'searxng'):
        if get('deployment', name, 'homelab-models')['spec'].get('replicas', 1) != 0:
            raise ValueError('Legacy writers must already be stopped by the reviewed Helm release')
    pods = run(['get', 'pods', '-n', 'homelab-models', '-o', 'json'])['items']
    if any(v.get('persistentVolumeClaim', {}).get('claimName') in CLAIMS and not is_terminated(p)
           for p in pods for v in p['spec'].get('volumes', [])):
        raise ValueError('An old AI claim still has a Pod')
    templates = {mode: get('configmap', 'quota-' + mode + '-template', 'homelab-platform')['data']['job.yaml']
                 for mode in ('admin', 'consumer')}
    proof = json.loads(get('configmap', 'quota-live-acceptance', 'homelab-platform')['data']['proof.json'])
    require_proof(proof, template_revision(templates), values['config']['filesystemUUID'],
                  get('node', 'talos-worker-01'), time.time())
    receipt = {'filesystem_uuid': values['config']['filesystemUUID'], 'source_commit': os.environ['GITHUB_SHA'],
               'quota_proof_run_id': proof['run_id'], 'claims': {}}
    for name in CLAIMS:
        claim = get('pvc', name, 'homelab-models')
        pv = get('pv', claim['spec']['volumeName'])
        if (pv['spec']['claimRef']['uid'] != claim['metadata']['uid'] or
                pv['spec']['claimRef']['namespace'] != 'homelab-models' or
                pv['spec']['persistentVolumeReclaimPolicy'] != 'Retain'):
            raise ValueError('Legacy retained PV binding mismatch')
        path = pv['spec']['hostPath']['path']
        if not path.startswith('/var/mnt/local-path-provisioner/'):
            raise ValueError('Legacy PV does not use the existing worker filesystem')
        receipt['claims'][name] = {'claim_uid': claim['metadata']['uid'], 'pv_uid': pv['metadata']['uid'],
                                  'pv_name': pv['metadata']['name'], 'basename': path.removeprefix('/var/mnt/local-path-provisioner/')}
    validate_receipt(receipt)
    # Creation is atomic and intentionally fails if any previous attempt exists.
    # Keep this receipt forever; deleting a Job does not grant permission to replay.
    record = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'immutable': True,
              'metadata': {'name': 'ai-volume-reset-v1', 'namespace': 'homelab-platform',
                           'annotations': {'homelab/reset-phase': 'prepared'}},
              'data': {'receipt.json': json.dumps(receipt, sort_keys=True)}}
    run(['create', '--raw', '/api/v1/namespaces/homelab-platform/configmaps?fieldValidation=Strict', '-f', '-'], record)
    template = get('configmap', 'ai-volume-reset-template', 'homelab-platform')['data']['job.yaml']
    job = yaml.safe_load(template)
    if job['metadata'] != {'name': 'ai-volume-reset-v1', 'namespace': 'homelab-platform'} or job['spec']['backoffLimit'] != 0:
        raise ValueError('Unexpected reset Job template')
    run(['create', '--raw', '/apis/batch/v1/namespaces/homelab-platform/jobs?fieldValidation=Strict', '-f', '-'], job)
    run(['wait', '-n', 'homelab-platform', 'job/ai-volume-reset-v1', '--for=condition=Complete', '--timeout=650s'])
    final = get('configmap', 'ai-volume-reset-v1', 'homelab-platform')
    if final['metadata']['annotations']['homelab/reset-phase'] != 'completed':
        raise ValueError('Reset completion was not observed')
    print('PASS: exact three-volume reset completed; immutable receipt retained and AI remains off')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Migration stopped; inspect the durable receipt and Job before manual recovery', file=sys.stderr)
        sys.exit(1)
