"""Private, bounded lifecycle maintenance operations shared by explicit CI recipes."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('homelab_apps', ROOT / 'scripts/homelab-apps.py')
apps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apps)
KUBECTL = os.environ.get('KUBECTL', str(Path.home() / '.cache/aws-account-infra/talos/kubectl-v1.36.3'))


class Maintenance:
    def __init__(self):
        if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('AI_MAINTENANCE_CONFIRM') != 'verify-ai-lifecycle-and-restore':
            raise apps.AppError('This explicit maintenance recipe requires reviewed protected CI')
        self.tokens = apps.lifecycle_credentials()
        self.created = []

    def kube(self, *arguments, value=None):
        return apps.run([KUBECTL, '--request-timeout=30s', *arguments],
                        None if value is None else json.dumps(value).encode())

    def get(self, namespace, kind, name):
        return json.loads(self.kube('-n', namespace, 'get', kind, name, '-o', 'json'))

    def api(self, path, payload=None, *, host='ai-lifecycle.tail2f646b.ts.net', token=None):
        token = token or self.tokens['operator']
        config = 'header = "Authorization: Bearer ' + token + '"\n'
        arguments = ['--fail-with-body', '--config', '-']
        if payload is not None:
            config += 'header = "Content-Type: application/json"\n'
            arguments += ['--data-binary', json.dumps(payload)]
        if host != 'ai-lifecycle.tail2f646b.ts.net':
            # Argo submissions with generateName are not safe to replay.
            return json.loads(apps.tailnet_https(host, path, arguments, config.encode()))
        # Lifecycle commands carry a stable UUID/revision. Retry only transient
        # observations/transport and storage-RV conflicts, never a semantic rejection.
        arguments.remove('--fail-with-body')
        arguments += ['--write-out', '\n%{http_code}']
        deadline = time.monotonic() + 30
        address = apps.tailnet_ip(host, deadline=deadline)
        for attempt in range(10):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise apps.AppError('Lifecycle API request deadline exceeded')
            budget = min(5, remaining)
            try:
                raw = apps.tailnet_https(host, path, [*arguments, '--max-time', str(budget)],
                                         config.encode(), address=address, timeout=budget)
            except apps.AppError:
                status, value = 0, {}
            else:
                body, _, code = raw.rpartition(b'\n')
                status = int(code)
                try:
                    value = json.loads(body)
                except ValueError:
                    value = {}
                if not isinstance(value, dict):
                    value = {}
                if status == 200:
                    if not isinstance(value, dict) or not value:
                        raise apps.AppError('Lifecycle API returned invalid successful state')
                    return value
            conflict = status == 409 and str(value.get('error', '')).startswith('State changed; retry the same command ID')
            if status not in (0, 408, 429, 500, 502, 503, 504) and not conflict:
                raise apps.AppError('Lifecycle API rejected request with HTTP ' + str(status))
            if attempt == 9 or time.monotonic() >= deadline:
                raise apps.AppError('Lifecycle API remained unavailable; last HTTP ' + str(status))
            time.sleep(max(0, min(1, deadline - time.monotonic())))

    def status(self):
        return self.api('/status')

    def command(self, operation, *, revision=None, command_id=None):
        revision = self.status()['revision'] if revision is None else revision
        return self.api('/' + operation, {'revision': revision, 'command_id': command_id or str(uuid.uuid4())})

    def wait(self, predicate, label, timeout=600):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.status()
            if predicate(value):
                print('PASS: ' + label, flush=True)
                return value
            time.sleep(3)
        raise apps.AppError('Timed out: ' + label)

    def off(self):
        value = self.status()
        if value['desired'] != 'off' or value['observed'] != 'Off':
            raise apps.AppError('Observed Off required before application-data maintenance')
        return value['revision']

    def unchanged_off(self, revision):
        if self.off() != revision:
            raise apps.AppError('Lifecycle command changed during capture; discard this backup')

    def fixture(self, key):
        data = self.get('homelab-models', 'configmap', 'ai-maintenance')['data']
        value = json.loads(data[key + '.json'])
        self.kube('create', '-f', '-', value=value)
        self.created.append(value['metadata']['name'])
        self.kube('-n', 'homelab-models', 'wait', 'pod/' + value['metadata']['name'],
                  '--for=condition=Ready', '--timeout=300s')
        return value['metadata']['name']

    def remove(self, name):
        self.kube('-n', 'homelab-models', 'delete', 'pod', name, '--wait=true', '--timeout=120s')
        self.created.remove(name)

    def cleanup(self):
        for name in list(reversed(self.created)):
            self.remove(name)


def private_environment():
    return {key: value for key, value in os.environ.items()
            if key not in apps.SECRET_NAMES and key not in ('GH_TOKEN', 'GITHUB_TOKEN')}
