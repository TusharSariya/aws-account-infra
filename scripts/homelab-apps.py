#!/usr/bin/env python3
"""Focused private-input, saved-plan and endpoint checks for application CI."""
import argparse
import base64
import hashlib
import ipaddress
import json
import os
import re
from pathlib import Path
import subprocess
import time
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TF = ROOT / 'live/kubernetes/homelab'
CONFIG = ROOT / 'config/environments/kubernetes/homelab'
SECRET_NAMES = ('TS_OPERATOR_CLIENT_ID', 'TS_OPERATOR_CLIENT_SECRET', 'PIHOLE_ADMIN_PASSWORD', 'GHCR_READ_USER', 'GHCR_READ_TOKEN', 'ODYSSEUS_ADMIN_PASSWORD', 'SEARXNG_SECRET', 'TALOS_SECRETS_B64')
class AppError(ValueError):
    """Only deliberately authored, secret-free diagnostics."""


ADDRESSES = {'helm_release.tailscale_operator', 'helm_release.pihole', 'helm_release.ollama', 'helm_release.odysseus', 'helm_release.capacity'}


def run(command, data=None):
    env = {k: v for k, v in os.environ.items() if k not in SECRET_NAMES}
    # Allow the operator (600s), dependent releases (900s), and cleanup/state writes.
    # Killing tofu at the Helm deadline leaves pending releases and a stale lock.
    result = subprocess.run(list(map(str, command)), input=data, capture_output=True, env=env, timeout=2400)
    if result.returncode:
        raise AppError('Private command failed: ' + Path(str(command[0])).name + '; diagnostics suppressed')
    return result.stdout


def setup():
    (TF / '.terraform').mkdir(parents=True, exist_ok=True)
    for name, artifact in json.loads((CONFIG / 'artifacts.json').read_text()).items():
        data = urllib.request.urlopen(artifact['url'], timeout=60).read()
        if hashlib.sha256(data).hexdigest() != artifact['sha256']:
            raise AppError('Chart checksum mismatch')
        (TF / '.terraform' / name).write_bytes(data)


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
    return values


def tailnet_ip(hostname):
    if hostname not in ('pve.tail2f646b.ts.net', 'pihole-admin.tail2f646b.ts.net', 'pihole-dns.tail2f646b.ts.net', 'odysseus.tail2f646b.ts.net', 'ollama.tail2f646b.ts.net'):
        raise AppError('Unexpected private HTTPS hostname')
    for attempt in range(12):
        status = json.loads(run(['tailscale', 'status', '--json']))
        peers = list((status.get('Peer') or {}).values()) + [status.get('Self') or {}]
        matches = [peer for peer in peers if peer.get('DNSName', '').rstrip('.').lower() == hostname]
        addresses = [ipaddress.ip_address(value) for peer in matches for value in peer.get('TailscaleIPs', [])]
        ipv4 = [address for address in addresses if address.version == 4]
        if ipv4:
            if len(ipv4) != 1 or ipv4[0] not in ipaddress.IPv4Network('100.64.0.0/10'):
                raise AppError('Expected exactly one private Tailscale IPv4 address for ' + hostname)
            return str(ipv4[0])
        if attempt < 11:
            time.sleep(5)
    raise AppError('Tailscale peer not visible after waiting: ' + hostname)


def tailnet_https(hostname, path, options):
    address = tailnet_ip(hostname)
    # Explicit address, original hostname/SNI and certificate verification intact.
    return run(['curl', '--silent', '--show-error', '--max-time', '30',
                '--resolve', hostname + ':443:' + address, *options, 'https://' + hostname + path])


def bootstrap(kubectl):
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise AppError('Credential reconciliation only runs in approved CI apply')
    values = credentials()
    # Do not change an independently managed namespace or create a parallel cluster.
    run([kubectl, 'get', 'namespace', 'homelab-services', 'homelab-models'])
    run([kubectl, 'apply', '--server-side', '--field-manager=homelab-app-credentials', '-f', CONFIG / 'namespaces.yaml'])
    for namespace, name, data in [
        ('tailscale', 'operator-oauth', {'client_id': values['TS_OPERATOR_CLIENT_ID'], 'client_secret': values['TS_OPERATOR_CLIENT_SECRET']}),
        ('homelab-services', 'pihole-admin', {'password': values['PIHOLE_ADMIN_PASSWORD']}),
        ('homelab-models', 'odysseus-bootstrap', {'admin-password': values['ODYSSEUS_ADMIN_PASSWORD'], 'searxng-secret': values['SEARXNG_SECRET']}),
        ('homelab-models', 'ghcr-read', {'.dockerconfigjson': json.dumps({'auths': {'ghcr.io': {'auth': base64.b64encode((values['GHCR_READ_USER'] + ':' + values['GHCR_READ_TOKEN']).encode()).decode()}}})})]:
        manifest = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': name, 'namespace': namespace},
                    'type': 'kubernetes.io/dockerconfigjson' if name == 'ghcr-read' else 'Opaque', 'data': {k: base64.b64encode(v.encode()).decode() for k, v in data.items()}}
        # Server-side apply avoids storing plaintext in a last-applied annotation.
        run([kubectl, 'apply', '--server-side', '--field-manager=homelab-app-credentials', '-f', '-'], json.dumps(manifest).encode())


def guard_plan(plan):
    if plan.get('resource_drift'):
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
    forbidden = [os.environ.get(name, '') for name in SECRET_NAMES[:-1] if name != 'GHCR_READ_USER']
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


def guard_images():
    import yaml
    ollama = yaml.safe_load((CONFIG / 'ollama-values.yaml').read_text())
    workspace = yaml.safe_load((CONFIG / 'workspace-values.yaml').read_text())
    images = [ollama['image'], workspace['image'], workspace['initImage']]
    images.extend(c['image'] for c in workspace['components'].values() if 'image' in c)
    if any(not re.fullmatch(r'[^\s@]+@sha256:[a-f0-9]{64}', image) for image in images):
        raise AppError('Every workspace image must use a reviewed immutable SHA-256 digest')
    if not workspace['image'].startswith('ghcr.io/tusharsariyaorg/homelab-odysseus@sha256:'):
        raise AppError('Workspace image must use the private homelab package')


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
        run(command + ['apply', '-input=false', '-lock-timeout=60s', plan])
        check_secrets(run(command + ['state', 'pull']), private)
        print('PASS: exact saved plan applied; application state excludes supplied credentials')


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
    for deployment in ['ollama', 'odysseus', 'chromadb', 'searxng']:
        run([kubectl, '-n', 'homelab-models', 'rollout', 'status', 'deployment/' + deployment, '--timeout=900s'])
    for service in ['ollama', 'odysseus']:
        run([kubectl, '-n', 'homelab-models', 'wait', 'ingress/' + service,
             '--for=jsonpath={.status.loadBalancer.ingress}', '--timeout=600s'])
    version = json.loads(tailnet_https('ollama.tail2f646b.ts.net', '/api/version', ['--fail']))
    if not version.get('version'):
        raise AppError('Ollama version endpoint did not return a version')
    tailnet_https('odysseus.tail2f646b.ts.net', '/api/health', ['--fail'])
    auth = tailnet_https('odysseus.tail2f646b.ts.net', '/api/conversations/topics',
                         ['-o', '/dev/null', '-w', '%{http_code}']).decode()
    if auth != '401':
        raise AppError('Workspace did not reject unauthenticated API access')
    print('PASS: private model API and authenticated workspace HTTPS; model/UI/restore acceptance remains separate')
    print(json.dumps({'dns_ip': ip, 'admin_url': url + '/admin/', 'status': 'DNS UDP/TCP and trusted HTTPS passed; client cutover remains explicit'}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['setup', 'credentials', 'resolve', 'bootstrap', 'plan', 'apply', 'endpoints'])
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
            if args.operation == 'bootstrap':
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
