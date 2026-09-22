#!/usr/bin/env python3
"""Keep Kueue webhooks out of platform and operational Pod admission."""
import sys
import yaml

def render(documents):
    touched = 0
    for document in documents:
        if not document:
            continue
        if document['kind'] in ('MutatingWebhookConfiguration', 'ValidatingWebhookConfiguration'):
            for hook in document['webhooks']:
                rules = hook.get('rules', [])
                # Kueue's own objects must retain their original validation.
                if any('kueue.x-k8s.io' in rule.get('apiGroups', []) for rule in rules):
                    continue
                hook['namespaceSelector'] = {'matchExpressions': [dict(
                    key='kubernetes.io/metadata.name', operator='In',
                    values=['homelab-models', 'homelab-jobs', 'arc-runners'])]}
                hook['objectSelector'] = {'matchExpressions': [dict(
                    key='kueue.x-k8s.io/queue-name', operator='Exists')]}
                if any('deployments' in rule.get('resources', []) for rule in rules):
                    # Lifecycle annotations/replicas and off-state template adoption do
                    # not need Kueue. Newly created Pods still fail closed at admission.
                    hook['matchConditions'] = hook.get('matchConditions', []) + [{
                        'name': 'template-admission-only',
                        'expression': "request.operation == 'CREATE' || (object.spec.replicas != 0 && object.spec.template != oldObject.spec.template)"}]
                hook['failurePolicy'] = 'Fail'
                touched += 1
        yield document
    if touched == 0:
        raise ValueError('Pinned chart has no workload webhooks; review upstream change')

if __name__ == '__main__':
    documents = list(render(yaml.safe_load_all(sys.stdin)))
    import subprocess
    from pathlib import Path
    rendered = yaml.safe_dump_all(documents, sort_keys=False)
    subprocess.run([str(Path(__file__).resolve().parents[1] / "kubernetes/platform/main/placement/helm-post-renderer.py"), "--namespace", "kueue-system"], input=rendered, text=True, check=True)
