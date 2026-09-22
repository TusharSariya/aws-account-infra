"""Refuse reconciliation while the primary worker is asleep or under maintenance."""
import json
import subprocess


def require_primary_ready(kubectl, env=None):
    command = list(kubectl) if isinstance(kubectl, (list, tuple)) else [str(kubectl)]
    def get(*args):
        return json.loads(subprocess.check_output(command + ['--request-timeout=20s', *args, '-o', 'json'], env=env))
    node = get('get', 'node', 'talos-worker-01')
    ready = any(c['type'] == 'Ready' and c['status'] == 'True'
                for c in node.get('status', {}).get('conditions', []))
    if not ready or node['spec'].get('unschedulable', False):
        raise ValueError('Primary worker is sleeping or cordoned; use the laptop wake runbook before applying')
    annotations = node.get('metadata', {}).get('annotations', {})
    if any(k in annotations for k in ('homelab.tfdraw.dev/power-operation', 'homelab.tfdraw.dev/power-intent')):
        raise ValueError('Power maintenance or platform restoration is still active')
    db = get('-n', 'homelab-data', 'get', 'clusters.postgresql.cnpg.io', 'apps-db')
    if db['metadata'].get('annotations', {}).get('cnpg.io/hibernation') == 'on':
        raise ValueError('Database maintenance is active; restore the saved maintenance journal first')
