#!/usr/bin/env python3
"""Focused private-input, saved-plan and endpoint checks for application CI."""
import argparse
import base64
import hashlib
import ipaddress
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import time
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from cache_download import fetch

sys.path.insert(0, str(ROOT / 'apps/platform/storage'))
from workload_state import is_terminated
TF = ROOT / 'live/kubernetes/homelab'
CONFIG = ROOT / 'config/environments/kubernetes/homelab'
SECRET_NAMES = ('TS_OPERATOR_CLIENT_ID', 'TS_OPERATOR_CLIENT_SECRET', 'PIHOLE_ADMIN_PASSWORD', 'GHCR_READ_USER', 'GHCR_READ_TOKEN', 'ODYSSEUS_ADMIN_PASSWORD', 'SEARXNG_SECRET', 'AI_LIFECYCLE_CREDENTIALS_B64', 'POSTGRES_BACKUP_CREDENTIALS_B64', 'TALOS_SECRETS_B64')
class AppError(ValueError):
    """Only deliberately authored, secret-free diagnostics."""


# Always-on releases are owned and guarded by homelab-management after migration.
ADDRESSES = {'helm_release.postgres_operator', 'helm_release.postgres',
             'helm_release.ollama', 'helm_release.odysseus',
             'helm_release.capacity', 'helm_release.ai'}


def run(command, data=None, *, timeout=2400):
    env = {k: v for k, v in os.environ.items() if k not in SECRET_NAMES and k not in ('GH_TOKEN', 'GITHUB_TOKEN')}
    # Allow the operator (600s), dependent releases (900s), and cleanup/state writes.
    # Killing tofu at the Helm deadline leaves pending releases and a stale lock.
    try:
        result = subprocess.run(list(map(str, command)), input=data, capture_output=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AppError("Private command timed out; diagnostics suppressed") from None
    if result.returncode:
        diagnostic = (result.stderr or b'').decode(errors='replace').lower()
        markers = {'openapi': 'schema-discovery', 'timeout': 'timeout', 'deadline exceeded': 'deadline',
                   'invalid ownership': 'ownership', 'already exists': 'already-exists',
                   'another operation': 'pending-operation', 'forbidden': 'forbidden',
                   'validation': 'validation', 'invalid': 'invalid', 'cannot re-use': 'release-name-in-use',
                   'provider produced inconsistent final plan': 'provider-inconsistent-final-plan',
                   'provider produced invalid plan': 'provider-invalid-plan',
                   'inconsistent result after apply': 'provider-inconsistent-result',
                   'error while running post render': 'post-render',
                   'error running post-renderer': 'post-render',
                   'failed to create patch': 'patch', 'cannot patch': 'patch',
                   'failed to render': 'render', 'failed to download': 'download',
                   'connection refused': 'connection-refused', 'no such host': 'dns',
                   'context canceled': 'canceled', 'error acquiring the state lock': 'state-lock'}
        categories = sorted({value for key, value in markers.items() if key in diagnostic})
        if categories:
            print('Application diagnostic categories: ' + ','.join(categories), file=sys.stderr)
        raise AppError('Private command failed: ' + Path(str(command[0])).name + '; diagnostics suppressed')
    return result.stdout


def setup():
    (TF / '.terraform').mkdir(parents=True, exist_ok=True)
    for name, artifact in json.loads((CONFIG / 'artifacts.json').read_text()).items():
        if os.environ.get('HOMELAB_DEPENDENCY_CACHE') == '1':
            fetch(artifact['url'], artifact['sha256'], TF / '.terraform' / name, use_cache=True)
            continue
        data = urllib.request.urlopen(artifact['url'], timeout=60).read()
        if hashlib.sha256(data).hexdigest() != artifact['sha256']:
            raise AppError('Chart checksum mismatch')
        (TF / '.terraform' / name).write_bytes(data)


def schema_readiness(kubectl):
    """Bounded read-only preflight before planning, with validation kept enabled."""
    for attempt in range(3):
        try:
            schema = json.loads(run([kubectl, '--request-timeout=20s', 'get', '--raw=/openapi/v2']))
            if schema.get('swagger') != '2.0' or not schema.get('definitions') or not schema.get('paths'):
                raise AppError('Kubernetes schema response is incomplete')
            print('PASS: authenticated Kubernetes schema discovery is readable')
            return
        except (AppError, json.JSONDecodeError):
            if attempt == 2:
                raise AppError('Kubernetes schema discovery unavailable after three bounded reads') from None
            time.sleep(2)


def credentials():
    values = {name: os.environ.get(name, '') for name in SECRET_NAMES[:-1]}
    if any(not value for value in values.values()):
        raise AppError('Set all application credentials in prod before apply; see docs/odysseus.md')
    if len(values['PIHOLE_ADMIN_PASSWORD']) < 20:
        raise AppError('Pi-hole password must contain at least 20 characters')
    if len(values['ODYSSEUS_ADMIN_PASSWORD'].encode()) not in range(20, 73):
        raise AppError('Odysseus password must be 20 to 72 UTF-8 bytes')
    if len(values['SEARXNG_SECRET']) < 32:
        raise AppError('SearxNG secret must contain at least 32 characters')
    lifecycle_credentials()
    from postgres_credentials import credentials as postgres_credentials
    postgres_credentials()
    return values


def lifecycle_credentials():
    try:
        values = json.loads(base64.b64decode(os.environ.get("AI_LIFECYCLE_CREDENTIALS_B64", ""), validate=True))
        if (set(values) != {"operator", "odysseus", "ollama", "model-user", "model-workspace"}
                or any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value) for value in values.values())
                or len(set(values.values())) != 5):
            raise ValueError()
        return values
    except (ValueError, TypeError):
        raise AppError("Five independent 256-bit lifecycle credentials are required") from None


def tailnet_ip(hostname, *, deadline=None):
    if hostname not in ('pve.tail2f646b.ts.net', 'pihole-admin.tail2f646b.ts.net', 'pihole-dns.tail2f646b.ts.net', 'odysseus.tail2f646b.ts.net', 'ollama.tail2f646b.ts.net', 'ai-lifecycle.tail2f646b.ts.net', 'argo.tail2f646b.ts.net'):
        raise AppError('Unexpected private HTTPS hostname')
    for attempt in range(12):
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise AppError('Private peer discovery deadline exceeded')
        options = {} if remaining is None else {'timeout': min(5, remaining)}
        status = json.loads(run(['tailscale', 'status', '--json'], **options))
        peers = list((status.get('Peer') or {}).values()) + [status.get('Self') or {}]
        matches = [peer for peer in peers if peer.get('DNSName', '').rstrip('.').lower() == hostname]
        addresses = [ipaddress.ip_address(value) for peer in matches for value in peer.get('TailscaleIPs', [])]
        ipv4 = [address for address in addresses if address.version == 4]
        if ipv4:
            if len(ipv4) != 1 or ipv4[0] not in ipaddress.IPv4Network('100.64.0.0/10'):
                raise AppError('Expected exactly one private Tailscale IPv4 address for ' + hostname)
            return str(ipv4[0])
        if attempt < 11:
            time.sleep(5 if deadline is None else max(0, min(5, deadline - time.monotonic())))
    raise AppError('Tailscale peer not visible after waiting: ' + hostname)


def tailnet_https(hostname, path, options, data=None, *, address=None, timeout=None):
    address = address or tailnet_ip(hostname)
    # Explicit address, original hostname/SNI and certificate verification intact.
    return run(['curl', '--silent', '--show-error', '--max-time', '30',
                '--resolve', hostname + ':443:' + address, *options, 'https://' + hostname + path], data, **({} if timeout is None else {'timeout': timeout}))


def reconcile_credential_object(kubectl, manifest):
    """Strict core API writes preserve metadata and use the observed version.

    Avoid OpenAPI discovery without disabling validation. No last-applied
    annotation is written, and credential content travels only through stdin.
    """
    metadata = manifest['metadata']
    kind, name, namespace = manifest['kind'], metadata['name'], metadata.get('namespace')
    allowed = {('Namespace', 'homelab-data', None),
               ('Secret', 'apps-db-backup-db', 'homelab-data'),
               ('Secret', 'apps-db-backup-identity', 'homelab-data'),
               ('Secret', 'ghcr-read', 'homelab-data'), ('Secret', 'operator-oauth', 'tailscale'),
               ('Secret', 'pihole-admin', 'homelab-services'),
               ('Secret', 'odysseus-bootstrap', 'homelab-models'),
               ('Secret', 'ghcr-read', 'homelab-models'), ('Namespace', 'tailscale', None),
               ('Secret', 'ai-lifecycle-credentials', 'homelab-platform'),
               ('Secret', 'ai-runtime-credentials', 'homelab-models'),
               ('Secret', 'ai-lifecycle-operator', 'homelab-jobs')}
    if manifest.get('apiVersion') != 'v1' or (kind, name, namespace) not in allowed:
        raise AppError('Unexpected credential object')
    path = '/api/v1/' + ('namespaces/' + namespace + '/secrets' if kind == 'Secret' else 'namespaces')
    existing = run([kubectl, '--request-timeout=30s', 'get', kind, name, '--ignore-not-found', '-o', 'json',
                    *(['-n', namespace] if namespace else [])])
    operation = 'create'
    if existing.strip():
        current = json.loads(existing)
        if not current['metadata'].get('resourceVersion'):
            raise AppError('Missing resource version for credential update')
        if kind == 'Secret':
            current['data'], current['type'] = manifest['data'], manifest['type']
            current['metadata'].setdefault('labels', {}).update(metadata.get('labels', {}))
        else:
            current['metadata'].setdefault('labels', {}).update(metadata.get('labels', {}))
        current.pop('status', None)
        manifest = current
        operation = 'replace'
        path += '/' + name
    run([kubectl, '--request-timeout=30s', operation, '--raw',
         path + '?fieldValidation=Strict&fieldManager=homelab-app-credentials', '-f', '-'], json.dumps(manifest).encode())


def bootstrap(kubectl):
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise AppError('Credential reconciliation only runs in approved CI apply')
    values = credentials()
    from postgres_credentials import reconcile
    reconcile(kubectl, reconcile_credential_object)
    # Do not change an independently managed namespace or create a parallel cluster.
    run([kubectl, 'get', 'namespace', 'homelab-services', 'homelab-models'])
    import yaml
    for manifest in yaml.safe_load_all((CONFIG / 'namespaces.yaml').read_text()):
        reconcile_credential_object(kubectl, manifest)
    lifecycle = lifecycle_credentials()
    for namespace, name, data in [
        ('homelab-platform', 'ai-lifecycle-credentials', {key: lifecycle[key] for key in ('operator', 'odysseus', 'ollama')}),
        ('homelab-models', 'ai-runtime-credentials', {key: lifecycle[key] for key in ('odysseus', 'ollama', 'model-user', 'model-workspace')}),
        ('tailscale', 'operator-oauth', {'client_id': values['TS_OPERATOR_CLIENT_ID'], 'client_secret': values['TS_OPERATOR_CLIENT_SECRET']}),
        ('homelab-services', 'pihole-admin', {'password': values['PIHOLE_ADMIN_PASSWORD']}),
        ('homelab-models', 'odysseus-bootstrap', {'admin-password': values['ODYSSEUS_ADMIN_PASSWORD'], 'searxng-secret': values['SEARXNG_SECRET']}),
        ('homelab-models', 'ghcr-read', {'.dockerconfigjson': json.dumps({'auths': {'ghcr.io': {'auth': base64.b64encode((values['GHCR_READ_USER'] + ':' + values['GHCR_READ_TOKEN']).encode()).decode()}}})})]:
        manifest = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': name, 'namespace': namespace},
                    'type': 'kubernetes.io/dockerconfigjson' if name == 'ghcr-read' else 'Opaque', 'data': {k: base64.b64encode(v.encode()).decode() for k, v in data.items()}}
        reconcile_credential_object(kubectl, manifest)
        if name == 'ghcr-read':
            manifest['metadata']['namespace'] = 'homelab-data'
            reconcile_credential_object(kubectl, manifest)


def reviewed_capacity_drift(drift, reviews):
    change = drift.get('change', {})
    before, after = change.get('before') or {}, change.get('after') or {}
    changed = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
    fingerprint = hashlib.sha256(json.dumps(drift, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    failed_revision = (before.get('status') in {'deployed', 'failed'}
                       and after.get('status') == 'failed' and changed <= {'metadata', 'status'})
    repaired_metadata = (before.get('status') == after.get('status') == 'deployed'
                         and changed == {'metadata'})
    return (drift.get('address') == 'helm_release.capacity' and change.get('actions') == ['update']
            and (failed_revision or repaired_metadata)
            and any(review.get('address') == drift['address'] and review.get('fingerprint') == fingerprint
                    for review in reviews))


def guard_plan(plan):
    reviews = json.loads((CONFIG / 'reviewed-drift.json').read_text())['reviews']
    unreviewed = [drift for drift in plan.get('resource_drift', []) if not reviewed_capacity_drift(drift, reviews)]
    if unreviewed:
        for drift in unreviewed:
            if drift.get('address') not in ADDRESSES:
                continue
            change = drift.get('change', {})
            before, after = change.get('before') or {}, change.get('after') or {}
            statuses = {'deployed', 'failed', 'pending-install', 'pending-upgrade', 'superseded', 'uninstalled'}
            print(json.dumps({'application_drift_review': {
                'address': drift['address'],
                'fingerprint': hashlib.sha256(json.dumps(drift, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                'changed_fields': sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key)),
                'before_status': before.get('status') if before.get('status') in statuses else 'other',
                'after_status': after.get('status') if after.get('status') in statuses else 'other'}}))
        raise AppError('Review application drift before deployment')
    summary = []
    for resource in plan.get('resource_changes', []):
        actions = resource['change']['actions']
        if resource['address'] not in ADDRESSES or actions not in (['no-op'], ['create'], ['update']):
            raise AppError('Unexpected application resource or destructive action')
        summary.append({'resource': resource['address'], 'actions': actions})
    if {item['resource'] for item in summary} != ADDRESSES:
        raise AppError('Plan must retain all application releases')
    return summary


def check_secrets(data, private):
    forbidden = [os.environ.get(name, '') for name in (*SECRET_NAMES[:-1], 'GH_TOKEN', 'GITHUB_TOKEN') if name != 'GHCR_READ_USER']
    if os.environ.get("AI_LIFECYCLE_CREDENTIALS_B64"):
        forbidden.extend(lifecycle_credentials().values())
    if os.environ.get('POSTGRES_BACKUP_CREDENTIALS_B64'):
        from postgres_credentials import credentials as postgres_credentials
        forbidden.extend(postgres_credentials().values())
    # Every credential in kubeconfig must stay out of provider state/plan.
    import yaml
    kube = yaml.safe_load((private / 'kubeconfig').read_text())
    for user in kube.get('users', []):
        forbidden.extend(str(v) for v in user.get('user', {}).values())
    forbidden.append((private / 'kubeconfig').read_text())
    text = data.decode()
    for value in forbidden:
        if value and (value in text or base64.b64encode(value.encode()).decode() in text):
            raise AppError('Credential appeared in private plan/state; refusing publication')


def guard_images(remote=None):
    import yaml
    ollama = yaml.safe_load((CONFIG / 'ollama-values.yaml').read_text())
    workspace = yaml.safe_load((CONFIG / 'workspace-values.yaml').read_text())
    ai = yaml.safe_load((CONFIG / 'ai-values.yaml').read_text())
    postgres = yaml.safe_load((CONFIG / 'postgres-values.yaml').read_text())
    operator = yaml.safe_load((CONFIG / 'postgres-operator-values.yaml').read_text())
    pg_images = [postgres['postgresImage'], 'ghcr.io/cloudnative-pg/cloudnative-pg:' + operator['image']['tag']]
    if postgres['backup']['enabled']:
        pg_images.append(postgres['backupImage'])
    images = pg_images + list(ai['images'].values()) + [ollama['image'], workspace['image'], workspace['initImage']]
    images.extend(c['image'] for c in workspace['components'].values() if 'image' in c)
    if any(not re.fullmatch(r'[^\s@]+@sha256:[a-f0-9]{64}', image) for image in images):
        raise AppError('Every workspace image must use a reviewed immutable SHA-256 digest')
    if not workspace['image'].startswith('ghcr.io/tusharsariyaorg/homelab-odysseus@sha256:'):
        raise AppError('Workspace image must use the private homelab package')
    spec = importlib.util.spec_from_file_location('verified_ai_images', ROOT / 'scripts/verify-ai-images.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        module.verify(ai['images'], remote=(os.environ.get('GITHUB_ACTIONS') == 'true' if remote is None else remote))
    except module.ImageError as error:
        raise AppError(str(error)) from None


def execute(operation, private):
    command = ['tofu', '-chdir=' + str(TF)]
    plan = private / 'apps.tfplan'
    guard_images()
    if operation == 'plan':
        run(command + ['plan', '-input=false', '-lock-timeout=60s', '-out=' + str(plan)])
        data = run(command + ['show', '-json', plan])
        check_secrets(data, private)
        summary = guard_plan(json.loads(data))
        (private / 'apps-plan.sha256').write_text(hashlib.sha256(plan.read_bytes()).hexdigest())
        print(json.dumps({'application_plan': summary}, indent=2))
    elif operation == 'apply':
        credentials()
        if os.environ.get('GITHUB_ACTIONS') != 'true':
            raise AppError('Application apply only runs through GitHub CI')
        if hashlib.sha256(plan.read_bytes()).hexdigest() != (private / 'apps-plan.sha256').read_text():
            raise AppError('Saved application plan changed after validation')
        from main_cluster_guard import require_primary_ready
        require_primary_ready(Path.home() / '.cache/aws-account-infra/talos/kubectl-v1.36.3')
        run([str(Path.home() / '.cache/aws-account-infra/talos/kubectl-v1.36.3'), 'apply', '-f', str(ROOT / 'kubernetes/platform/main/placement/proxy-class.yaml')])
        from postgres_preflight import verify
        verify(str(Path.home() / '.cache/aws-account-infra/talos/kubectl-v1.36.3'), run)
        try:
            run(command + ['apply', '-input=false', '-lock-timeout=60s', plan])
        except AppError:
            try:
                status = run([str(Path.home() / '.cache/aws-account-infra/talos/kubectl-v1.36.3'),
                    '--request-timeout=30s', '-n', 'kube-system', 'get', 'secret',
                    '-l', 'owner=helm,name=homelab-capacity',
                    '-o', 'jsonpath={.items[*].metadata.labels.status}']).decode()
                observed = [value for value in status.split() if value in
                            ('deployed', 'failed', 'pending-install', 'pending-upgrade', 'pending-rollback')]
                print('Capacity release states: ' + ','.join(observed or ['unknown' if status.strip() else 'absent']), file=sys.stderr)
            except Exception:
                print('Capacity release state unavailable', file=sys.stderr)
            raise
        lifecycle = lifecycle_credentials()
        reconcile_credential_object(Path.home() / '.cache/aws-account-infra/talos/kubectl-v1.36.3', {
            'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'ai-lifecycle-operator', 'namespace': 'homelab-jobs'},
            'type': 'Opaque', 'data': {'operator': base64.b64encode(lifecycle['operator'].encode()).decode()}})
        check_secrets(run(command + ['state', 'pull']), private)
        print('PASS: exact saved plan applied; application state excludes supplied credentials')


def verify_ai_off(kubectl):
    """Packaging-stage acceptance observes shutdown; it never scales a writer."""
    legacy = ('ollama', 'odysseus', 'chromadb', 'searxng')
    deployments = json.loads(run([kubectl, '-n', 'homelab-models', 'get', 'deployment', *legacy, '-o', 'json']))
    if {item['metadata']['name'] for item in deployments['items']} != set(legacy) or any(
            item['spec'].get('replicas', 1) != 0 for item in deployments['items']):
        raise AppError('Legacy AI writers must remain explicitly off')
    runtime = run([kubectl, '-n', 'homelab-models', 'get', 'deployment', 'ai-runtime', '--ignore-not-found', '-o', 'json'])
    if runtime.strip():
        runtime = json.loads(runtime)
        if (runtime['spec'].get('replicas', 1) != 0 or
                runtime['metadata'].get('annotations', {}).get('homelab/desired-state') != 'off'):
            raise AppError('Runtime must remain off until lifecycle activation')
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        pods = json.loads(run([kubectl, '--request-timeout=30s', '-n', 'homelab-models', 'get', 'pods',
                              '-l', 'app in (ollama,odysseus,chromadb,searxng,ai-runtime)', '-o', 'json']))
        if all(is_terminated(pod) for pod in pods['items']):
            return
        time.sleep(3)
    raise AppError('AI still has active or unverified Pods after shutdown deadline')


def verify_lifecycle(kubectl):
    """Read the authenticated controller without issuing Start or changing intent."""
    token = lifecycle_credentials()['operator']
    host = 'ai-lifecycle.tail2f646b.ts.net'
    run([kubectl, '-n', 'homelab-platform', 'rollout', 'status', 'deployment/ai-lifecycle', '--timeout=300s'])
    run([kubectl, '-n', 'homelab-platform', 'wait', 'ingress/ai-lifecycle',
         '--for=jsonpath={.status.loadBalancer.ingress}', '--timeout=300s'])
    if tailnet_https(host, '/status', ['-o', '/dev/null', '-w', '%{http_code}']).decode() != '401':
        raise AppError('Lifecycle API must reject unauthenticated access')
    # Credentials travel through curl stdin, never command arguments or logs.
    status = json.loads(tailnet_https(host, '/status', ['--fail', '--config', '-'],
        ('header = "Authorization: Bearer ' + token + '"\n').encode()))
    if (status.get('desired') not in ('on', 'off') or status.get('observed') not in
            ('Off', 'On', 'Starting/Pending', 'Draining', 'Stopping') or type(status.get('revision')) is not int):
        raise AppError('Lifecycle Status is not verified')
    if status['observed'] == 'Off':
        verify_ai_off(kubectl)
        print('PASS: AI intentionally off; CI did not start it')
    else:
        legacy = json.loads(run([kubectl, '-n', 'homelab-models', 'get', 'deployment',
            'ollama', 'odysseus', 'chromadb', 'searxng', '-o', 'json']))
        if len(legacy['items']) != 4 or any(item['spec'].get('replicas', 1) != 0 for item in legacy['items']):
            raise AppError('Legacy AI writers must remain off')
        print('PASS: lifecycle owns runtime intent; observed ' + status['observed'])
    return status


def endpoints(kubectl):
    run([kubectl, '-n', 'homelab-services', 'rollout', 'status', 'deployment/pihole', '--timeout=600s'])
    run([kubectl, '-n', 'tailscale', 'rollout', 'status', 'deployment/operator', '--timeout=600s'])
    # Annotated ClusterIP Services expose a proxy condition, not LoadBalancer status.
    run([kubectl, '-n', 'homelab-services', 'wait', 'service/pihole-dns',
         '--for=condition=TailscaleProxyReady=true', '--timeout=600s'])
    run([kubectl, '-n', 'homelab-services', 'wait', 'ingress/pihole',
         '--for=jsonpath={.status.loadBalancer.ingress}', '--timeout=600s'])
    ip = tailnet_ip('pihole-dns.tail2f646b.ts.net')
    for transport in ['+notcp', '+tcp']:
        allowed = run(['dig', '@' + ip, 'example.com', 'A', '+short', '+time=5', '+tries=2', transport]).decode()
        if not allowed.strip() or '0.0.0.0' in allowed:
            raise AppError('Allowed DNS query failed')
        blocked = run(['dig', '@' + ip, 'doubleclick.net', 'A', '+short', '+time=5', '+tries=2', transport]).decode()
        if blocked.strip() != '0.0.0.0':
            raise AppError('Standard blocklist DNS query did not return the configured block response')
    url = 'https://pihole-admin.tail2f646b.ts.net'
    tailnet_https('pihole-admin.tail2f646b.ts.net', '/admin/', ['--fail'])
    status = tailnet_https('pihole-admin.tail2f646b.ts.net', '/api/domains',
                           ['-o', '/dev/null', '-w', '%{http_code}']).decode()
    if status != '401':
        raise AppError('Pi-hole administration did not reject unauthenticated API access')
    verify_lifecycle(kubectl)
    print(json.dumps({'dns_ip': ip, 'admin_url': url + '/admin/', 'status': 'DNS UDP/TCP and trusted HTTPS passed; client cutover remains explicit'}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['setup', 'credentials', 'resolve', 'schema', 'bootstrap', 'plan', 'apply', 'endpoints'])
    parser.add_argument('--private', type=Path)
    parser.add_argument('--hostname')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.operation == 'credentials':
            credentials()
            print('PASS: application credential inputs present')
        elif args.operation == 'resolve':
            print(tailnet_ip(args.hostname))
        elif args.operation == 'setup':
            setup()
        else:
            private = args.private.resolve()
            if private.stat().st_mode & 0o077 or private.stat().st_uid != os.getuid():
                raise AppError('Private workspace must be owned by this user with mode 0700')
            os.environ['KUBECONFIG'] = str(private / 'kubeconfig')
            os.environ['TF_VAR_kubeconfig_path'] = str(private / 'kubeconfig')
            kubectl = Path.home() / '.cache/aws-account-infra/talos/kubectl-v1.36.3'
            if args.operation == 'schema':
                schema_readiness(kubectl)
            elif args.operation == 'bootstrap':
                bootstrap(kubectl)
            elif args.operation == 'endpoints':
                endpoints(kubectl)
            else:
                execute(args.operation, private)
    except Exception as error:
        print(str(error) if isinstance(error, AppError) else 'Application operation failed; private diagnostics suppressed', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
