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
        return json.loads(apps.tailnet_https(host, path, arguments, config.encode()))

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
