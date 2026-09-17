#!/usr/bin/env python3
"""Independent hosted/Mac bootstrap with immutable artifacts and exact saved plans."""
import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import yaml
from kueue_capacity import verify
from local_lifecycle_record import execution_lock, guard_environment, tree_digest

ROOT = Path(__file__).resolve().parents[1]
TF = ROOT / 'live/kubernetes/homelab-ci'
CONFIG = ROOT / 'config/environments/kubernetes/homelab-ci'
RELEASES = {'kueue': ('kueue-system', '0.19.4'), 'queue': ('kueue-system', None),
            'arc': ('arc-systems', '0.14.2'), 'cache': ('homelab-cache', None), 'runners': ('arc-runners', '0.14.2')}


def run(args, data=None):
    result = subprocess.run(list(map(str, args)), input=data, capture_output=True, timeout=1800)
    if os.environ.get('HOMELAB_CI_LOG_DIR') and (result.returncode or 'apply' in args):
        destination = Path(os.environ['HOMELAB_CI_LOG_DIR']) / (str(time.time_ns()) + '-command.log')
        destination.write_bytes(result.stdout + b'\n' + result.stderr)
        destination.chmod(0o600)
    if result.returncode:
        raise ValueError('Command failed: ' + Path(str(args[0])).name + '; private output suppressed')
    return result.stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def guard(plan):
    if plan.get('errored') or plan.get('complete') is False or plan.get('deferred_changes'):
        raise ValueError('Complete successful plan required')
    changes = []
    for obj in plan.get('resource_changes', []):
        change = obj['change']
        if change['actions'] == ['no-op']:
            continue
        name = obj['address'].removeprefix('helm_release.')
        match = re.fullmatch(r'runners\["([^"]+)"\]', name)
        if match:
            catalog = json.loads((CONFIG / 'runner-catalog.json').read_text())
            if match[1] not in catalog or change['after'].get('name') != match[1]:
                raise ValueError('Unknown runner scale set')
            name = 'runners'
        if ((not match and obj['address'] != 'helm_release.' + name) or name not in RELEASES
                or change['actions'] not in (['create'], ['update'])):
            raise ValueError('Unexpected CI infrastructure change: ' + obj['address'])
        namespace, version = RELEASES[name]
        if change['after'].get('namespace') != namespace or (version and change['after'].get('version') != version):
            raise ValueError('Unapproved release namespace/version')
        changes.append(obj['address'])
    return changes


def backend():
    value = json.loads((TF / '.terraform/terraform.tfstate').read_text())['backend']
    expected = dict(bucket='tofu-state-992382747916-us-east-1', key='kubernetes/homelab-ci/terraform.tfstate',
                    region='us-east-1', dynamodb_table='tofu-locks', encrypt=True)
    if value['type'] != 's3' or any(value['config'].get(k) != v for k, v in expected.items()):
        raise ValueError('CI backend identity differs')
    if any(v for k, v in value['config'].items() if ('endpoint' in k or k.startswith('skip_') or k in ('insecure','use_path_style','force_path_style'))):
        raise ValueError('Backend endpoint/validation overrides are forbidden')
    if run(['tofu', '-chdir=' + str(TF), 'workspace', 'show']).strip() != b'default':
        raise ValueError('Default workspace required')


def artifacts():
    (TF / '.terraform').mkdir(exist_ok=True)
    for artifact in json.loads((CONFIG / 'artifacts.json').read_text()):
        path = TF / '.terraform' / (artifact['chart'] + '-' + artifact['version'] + '.tgz')
        if not path.exists():
            run(['helm', 'pull', artifact['registry'] + '/' + artifact['chart'], '--version', artifact['version'], '--destination', path.parent])
        if path.is_symlink() or sha(path) != artifact['sha256']:
            raise ValueError('Pinned Helm artifact checksum differs: ' + artifact['chart'])


def preflight(kube):
    def get(*args):
        return json.loads(run(kube + list(args) + ['-o', 'json']))
    deployment = get('get', 'deployment', 'ai-runtime', '-n', 'homelab-models')
    pods = get('get', 'pods', '--all-namespaces')['items']
    if deployment['spec']['replicas'] != 0 or any(
            p['metadata']['namespace'] == 'homelab-models' and p['metadata'].get('labels', {}).get('app') == 'ai-runtime'
            and p.get('status', {}).get('phase') not in ('Succeeded', 'Failed') for p in pods):
        raise ValueError('Keep AI off with termination observed throughout migration')
    config = yaml.safe_load((CONFIG / 'pool-values.yaml').read_text())
    catalog = json.loads((CONFIG / 'runner-catalog.json').read_text())
    # Updating a scale set must not interrupt an assigned or gated runner.
    if any(p['metadata']['namespace'] == 'arc-runners'
           and 'kueue.x-k8s.io/queue-name' in p['metadata'].get('labels', {})
           and p.get('status', {}).get('phase') not in ('Succeeded', 'Failed') for p in pods):
        raise ValueError('Wait for all existing runners to become idle before admission deployment')
    node = get('get', 'node', 'talos-worker-01')
    summary = json.loads(run(kube + ['get', '--raw=/api/v1/nodes/talos-worker-01/proxy/stats/summary']))
    from kueue_capacity import verify_storage
    # Include every desired listener, even if the scheduler places it elsewhere.
    existing = {p['metadata'].get('labels', {}).get('actions.github.com/scale-set-name') for p in pods
                if any(o.get('kind') == 'AutoscalingListener' for o in p['metadata'].get('ownerReferences', []))}
    projected = list(pods)
    listener = yaml.safe_load((CONFIG / 'arc-runner-values.yaml').read_text())['listenerTemplate']
    import copy
    for name in set(catalog) - existing:
        pod = copy.deepcopy(listener)
        pod['metadata'] = {'labels': {}}
        pod['spec']['nodeName'] = 'talos-worker-01'
        projected.append(pod)
    # Cache Pods are outside Kueue but consume the approved platform reserve.
    cache_values = yaml.safe_load((ROOT / 'charts/homelab-cache/values.yaml').read_text())
    # Render every desired service and transient job; include whole-Pod init
    # requests and reserve one monitoring/configuration slot even while idle.
    rendered = run(['helm', 'template', 'homelab-cache', ROOT / 'charts/homelab-cache', '-f', '-'],
                   yaml.safe_dump({'configure': True, 'volumes': json.loads((CONFIG / 'cache-storage.json').read_text())}).encode())
    for resource in yaml.safe_load_all(rendered):
        if not resource or resource.get('kind') not in ('Deployment', 'Job', 'CronJob'):
            continue
        template = (resource['spec']['jobTemplate']['spec']['template'] if resource['kind'] == 'CronJob'
                    else resource['spec']['template'])
        app = template['metadata']['labels']['app']
        if not any(p['metadata'].get('namespace') == 'homelab-cache' and
                   p['metadata'].get('labels', {}).get('app') == app and
                   p.get('status', {}).get('phase') not in ('Succeeded', 'Failed') for p in projected):
            pod = copy.deepcopy(template)
            pod['spec']['nodeName'] = config['worker']
            projected.append(pod)
    from cache_capacity import verify_cache_storage
    guest = json.loads(get('get', 'configmap', 'guest-capacity', '-n', 'homelab-platform')['data']['sample.json'])
    physical = json.loads(get('get', 'configmap', 'physical-capacity', '-n', 'homelab-platform')['data']['sample.json'])
    storage = json.loads((CONFIG / 'cache-storage.json').read_text())
    capacity_config = yaml.safe_load((ROOT / 'config/environments/kubernetes/homelab/capacity-values.yaml').read_text())['config']
    cache_report = verify_cache_storage(guest, physical, storage, capacity_config, get('get', 'pv')['items'])
    images = {name for item in node['status'].get('images', []) for name in item['names']}
    for image in cache_values['images'].values():
        digest = image.split('@')[1]
        if not any(name.endswith('@' + digest) for name in images):
            raise ValueError('Preload pinned Nexus/PostgreSQL images before fresh scratch measurement')
    report = verify(node, projected, config['platformReserve'], config)
    report['cache_storage'] = cache_report
    report['storage_and_slots'] = verify_storage(node, projected, summary, config, catalog)
    run(kube + ['-n', 'homelab-services', 'rollout', 'status', 'deployment/pihole', '--timeout=60s'])
    # Resolve the exact peer through Tailscale, independent of Mac MagicDNS.
    from lifecycle_session import apps
    dns_address = apps.tailnet_ip('pihole-dns.tail2f646b.ts.net')
    for transport in ['+tcp', '+notcp']:
        answer = run(['dig', '@' + dns_address, 'example.com', 'A', '+short', '+time=5', '+tries=2', transport]).decode()
        if not answer.strip() or '0.0.0.0' in answer or 'timed out' in answer:
            raise ValueError('Pi-hole TCP/UDP DNS verification failed')
    return report


def enroll(kube, source):
    if not source or source.is_symlink() or source.stat().st_mode & 0o077 or source.stat().st_uid != os.getuid():
        raise ValueError('Provide a private owned GitHub App JSON file')
    value = json.loads(source.read_text())
    required = {'github_app_id','github_app_installation_id','github_app_private_key'}
    if set(value) != required or any(not isinstance(v, str) or not v for v in value.values()):
        raise ValueError('GitHub App JSON must contain exactly the three ARC string fields')
    # Namespace is adopted by the queue Helm release. No credential enters OpenTofu.
    namespace = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': 'arc-runners',
                 'labels': {'pod-security.kubernetes.io/enforce': 'privileged', 'app.kubernetes.io/managed-by': 'Helm'},
                 'annotations': {'meta.helm.sh/release-name': 'homelab-queue', 'meta.helm.sh/release-namespace': 'kueue-system'}}}
    run(kube + ['apply', '-f', '-'], json.dumps(namespace).encode())
    secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'github-app', 'namespace': 'arc-runners'},
              'type': 'Opaque', 'data': {k: base64.b64encode(v.encode()).decode() for k, v in value.items()}}
    # Server-side apply avoids a duplicate private last-applied annotation.
    run(kube + ['apply', '--server-side', '--field-manager=homelab-ci-credentials', '-f', '-'], json.dumps(secret).encode())


def enroll_cache(kube, source):
    if (not source or source.is_symlink() or source.stat().st_mode & 0o077
            or source.stat().st_uid != os.getuid()):
        raise ValueError('Private owned cache credentials file required')
    value = json.loads(source.read_text())
    if set(value) != {'database', 'admin-password', 'build-password', 'metrics-password'} or any(
            not isinstance(v, str) or len(v) < 32 for v in value.values()):
        raise ValueError('Cache credentials require four distinct strong secrets')
    if len(set(value.values())) != 4:
        raise ValueError('Cache credential roles must not share passwords')
    namespace = {'apiVersion':'v1', 'kind':'Namespace', 'metadata':{'name':'homelab-cache',
        'labels':{'app.kubernetes.io/managed-by':'Helm','pod-security.kubernetes.io/enforce':'restricted'},
        'annotations':{'meta.helm.sh/release-name':'homelab-cache','meta.helm.sh/release-namespace':'homelab-cache'}}}
    run(kube + ['apply','--server-side','--field-manager=homelab-cache-credentials','-f','-'],json.dumps(namespace).encode())
    for name, data in [('nexus-database', {'password':value['database']}),
                       ('nexus-administrator', {k:value[k] for k in ('admin-password','build-password','metrics-password')})]:
        manifest = {'apiVersion':'v1','kind':'Secret','metadata':{'name':name,'namespace':'homelab-cache'},
                    'type':'Opaque','data':{k:base64.b64encode(v.encode()).decode() for k,v in data.items()}}
        run(kube + ['apply','--server-side','--field-manager=homelab-cache-credentials','-f','-'],json.dumps(manifest).encode())



def enroll_registry(kube, source):
    if (not source or source.is_symlink() or source.stat().st_mode & 0o077
            or source.stat().st_uid != os.getuid()):
        raise ValueError('Private owned registry configuration file required')
    value = json.loads(source.read_text())
    if set(value) != {'auths'} or set(value['auths']) != {'ghcr.io'}:
        raise ValueError('Only the reviewed GHCR registry may be enrolled')
    entry = value['auths']['ghcr.io']
    if set(entry) != {'auth'}:
        raise ValueError('A single GHCR Basic credential is required')
    identity, token = base64.b64decode(entry['auth'], validate=True).decode().split(':', 1)
    if not identity or not token:
        raise ValueError('Registry identity and token required')
    request = urllib.request.Request('https://api.github.com/user', headers={
        'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args): return None
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
        scopes = {scope.strip() for scope in response.headers.get('X-OAuth-Scopes', '').split(',') if scope.strip()}
        if scopes != {'read:packages'}:
            raise ValueError('Runner image pull credential must have only read:packages scope')
    secret = {'apiVersion': 'v1', 'kind': 'Secret',
              'metadata': {'name': 'ghcr-read', 'namespace': 'arc-runners'},
              'type': 'kubernetes.io/dockerconfigjson',
              'data': {'.dockerconfigjson': base64.b64encode(json.dumps(value).encode()).decode()}}
    run(kube + ['apply', '--server-side', '--field-manager=homelab-ci-credentials', '-f', '-'], json.dumps(secret).encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['setup','plan','apply','enroll','enroll-cache','enroll-registry','status'])
    parser.add_argument('--private', type=Path)
    parser.add_argument('--app-json', type=Path)
    parser.add_argument('--cache-json', type=Path)
    parser.add_argument('--registry-json', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    guard_environment()
    if any(k.startswith(('AWS_ENDPOINT_URL','TF_VAR_','TOFU_CLI_ARGS')) for k in os.environ):
        raise ValueError('Endpoint, variable and CLI overrides are forbidden')
    if args.operation in ('setup', 'plan', 'apply'):
        from runner_catalog import catalog, validate_workflows
        catalog()
        validate_workflows()
        artifacts()
    if args.operation == 'setup':
        print('PASS: pinned Helm archives verified')
        return
    private = args.private.resolve()
    if private.stat().st_mode & 0o077 or private.stat().st_uid != os.getuid():
        raise ValueError('Use a private owned workspace')
    os.environ['HOMELAB_CI_LOG_DIR'] = str(private)
    kubeconfig = private / 'kubeconfig'
    if kubeconfig.is_symlink() or kubeconfig.stat().st_mode & 0o077:
        raise ValueError('Private regular kubeconfig required')
    os.environ['TF_VAR_kubeconfig_path'] = str(kubeconfig)
    kube = ['kubectl', '--kubeconfig', str(kubeconfig), '--request-timeout=30s']
    if args.operation == 'status':
        value = json.loads(run(kube + ['get', 'workloads.kueue.x-k8s.io', '-A', '-o', 'json']))
        summary = json.loads(run(kube + ['get', '--raw=/apis/visibility.kueue.x-k8s.io/v1beta2/clusterqueues/homelab-compute/pendingworkloads']))
        positions = {(w['metadata']['namespace'], w['metadata']['name']): w['positionInClusterQueue'] + 1 for w in summary['items']}
        waiting, reserved = [], []
        for obj in sorted(value['items'], key=lambda w: (w['metadata'].get('creationTimestamp',''), w['metadata']['name'])):
            if any(c['type'] == 'Finished' and c['status'] == 'True' for c in obj.get('status', {}).get('conditions', [])):
                continue
            info = {'namespace': obj['metadata']['namespace'], 'name': obj['metadata']['name'],
                    'queue': obj['spec']['queueName'], 'created_at': obj['metadata'].get('creationTimestamp'),
                    'conditions': obj.get('status', {}).get('conditions', []),
                    'reserved': obj.get('status', {}).get('admission', {}).get('podSetAssignments', [])}
            from kueue_capacity import requests
            info['waiting_position'] = positions.get((info['namespace'], info['name']))
            info['requested'] = {r: str(sum(requests(p['template'], r) * p['count'] for p in obj['spec']['podSets'])) for r in ['cpu','memory','ephemeral-storage']}
            (reserved if info['reserved'] else waiting).append(info)
        print(json.dumps({'waiting_fifo': sorted(waiting, key=lambda w: (w['waiting_position'] is None, w['waiting_position'] or 0)), 'reserved': reserved}, indent=2))
        return
    with execution_lock():
        if args.operation == 'enroll-registry':
            enroll_registry(kube, args.registry_json)
            print('PASS: read-only runner image credential enrolled privately')
            return
        if args.operation == 'enroll-cache':
            enroll_cache(kube, args.cache_json)
            print('PASS: cache credentials enrolled privately')
            return
        if args.operation == 'enroll':
            enroll(kube, args.app_json)
            print('PASS: GitHub App Secret enrolled privately')
            return
        backend()
        report = preflight(kube)
        command = ['tofu', '-chdir=' + str(TF)]
        plan, receipt = private / 'ci.tfplan', private / 'ci-record.json'
        if args.operation == 'plan':
            if receipt.exists() or plan.exists():
                raise ValueError('Use a new private directory to retain previous attempts')
            source = tree_digest()
            run(command + ['plan','-input=false','-lock-timeout=60s','-out=' + str(plan)])
            changes = guard(json.loads(run(command + ['show','-json',plan])))
            if source != tree_digest():
                raise ValueError('Source changed during planning')
            receipt.write_text(json.dumps(dict(source=source, plan=sha(plan), kubeconfig=sha(kubeconfig),
                time=time.time(), apply='not-started', capacity=report, changes=changes,
                execution='github' if os.environ.get('GITHUB_ACTIONS') == 'true' else 'local'), indent=2))
            print(json.dumps({'changes': changes, 'capacity': report}, indent=2))
            return
        record = json.loads(receipt.read_text())
        if (record['source'] != tree_digest() or record['plan'] != sha(plan) or record['kubeconfig'] != sha(kubeconfig)
                or not 0 <= time.time() - record['time'] <= 3600 or record['apply'] != 'not-started'):
            raise ValueError('Source, identity or saved plan changed, expired or already attempted')
        guard(json.loads(run(command + ['show','-json',plan])))
        record['apply'] = 'running'; receipt.write_text(json.dumps(record, indent=2))
        try:
            run(command + ['apply','-input=false','-lock-timeout=60s',plan])
            record['apply'] = 'success'
            fresh = private / 'post-apply.tfplan'
            run(command + ['plan','-input=false','-lock-timeout=60s','-out=' + str(fresh)])
            if guard(json.loads(run(command + ['show','-json',fresh]))):
                raise ValueError('Post-deployment plan is not empty')
            record['post_plan_empty'] = True
        except Exception:
            record['apply'] = 'failed-or-verification-incomplete'
            raise
        finally:
            receipt.write_text(json.dumps(record, indent=2))
        print('PASS: saved plan applied and fresh post-deployment plan empty; runtime acceptance remains required')

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error) if isinstance(error, ValueError) else 'CI operation failed; private diagnostics suppressed', file=sys.stderr)
        raise SystemExit(1) from None
