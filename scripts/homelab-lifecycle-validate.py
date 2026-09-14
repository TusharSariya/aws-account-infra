#!/usr/bin/env python3
"""Non-disruptive lifecycle, private Argo authentication and admission checks."""
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('homelab_apps', ROOT / 'scripts/homelab-apps.py')
apps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apps)
KUBECTL = Path.home() / '.cache/aws-account-infra/talos/kubectl-v1.36.3'
CLIENT = 'system:serviceaccount:homelab-jobs:homelab-workflow-client'


def dry_run(value, accepted):
    result = subprocess.run([str(KUBECTL), '--request-timeout=20s', '--as=' + CLIENT,
        'create', '--dry-run=server', '-f', '-'], input=json.dumps(value).encode(), capture_output=True, timeout=30)
    if accepted != (result.returncode == 0):
        raise apps.AppError('Reviewed Workflow admission contract failed')
    if not accepted and b'homelab-reviewed-workflows' not in result.stderr:
        raise apps.AppError('Workflow rejection was not enforced by the reviewed policy')


def main():
    apps.verify_lifecycle(KUBECTL)
    for name in ('homelab-reviewed-workflows', 'homelab-lifecycle-runtime'):
        policy = json.loads(apps.run([KUBECTL, 'get', 'validatingadmissionpolicy', name, '-o', 'json']))
        if policy.get('status', {}).get('observedGeneration') != policy['metadata']['generation']:
            raise apps.AppError('Admission policy has not been observed')
        if policy.get('status', {}).get('typeChecking', {}).get('expressionWarnings'):
            raise apps.AppError('Admission expression type checking failed')
        binding = json.loads(apps.run([KUBECTL, 'get', 'validatingadmissionpolicybinding', name, '-o', 'json']))
        if binding['spec']['policyName'] != name or binding['spec']['validationActions'] != ['Deny']:
            raise apps.AppError('Admission binding is not enforcing the reviewed policy')
    workflow = {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Workflow',
        'metadata': {'generateName': 'admission-proof-', 'namespace': 'homelab-jobs'},
        'spec': {'workflowTemplateRef': {'name': 'smoke'}}}
    dry_run(workflow, True)
    for key, value in {'serviceAccountName': 'argo-controller', 'hostNetwork': True,
                       'podSpecPatch': '{"hostPID":true}', 'templates': [],
                       'workflowMetadata': {'labels': {'homelab/lifecycle-operation': 'true'}}}.items():
        dry_run({**workflow, 'spec': {**workflow['spec'], key: value}}, False)
    host = 'argo.tail2f646b.ts.net'
    apps.run([KUBECTL, '-n', 'homelab-jobs', 'rollout', 'status', 'deployment/argo-workflows-server', '--timeout=300s'])
    apps.run([KUBECTL, '-n', 'homelab-jobs', 'wait', 'ingress/argo', '--for=jsonpath={.status.loadBalancer.ingress}', '--timeout=300s'])
    path = '/api/v1/workflows/homelab-jobs'
    rejected = apps.tailnet_https(host, path, ['-o', '/dev/null', '-w', '%{http_code}']).decode()
    if rejected not in ('401', '403'):
        raise apps.AppError('Argo API did not reject unauthenticated access')
    token = apps.run([KUBECTL, '-n', 'homelab-jobs', 'create', 'token', 'homelab-workflow-client', '--duration=10m']).decode().strip()
    result = json.loads(apps.tailnet_https(host, path, ['--fail', '--config', '-'],
        ('header = "Authorization: Bearer ' + token + '"\n').encode()))
    if 'items' not in result and result.get('metadata') is None:
        raise apps.AppError('Authenticated Argo response invalid')
    print('PASS: private client-token Argo API and denied Workflow privilege overrides; no work was submitted')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit(str(error) if isinstance(error, apps.AppError) else 'Lifecycle acceptance failed; private diagnostics suppressed') from None
