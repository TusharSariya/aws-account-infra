#!/usr/bin/env python3
"""Explicit protected CI behavior rehearsal; no migration reset or host edits."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import base64
import json
import os
import signal
from pathlib import Path
import time
import tempfile
import uuid

from lifecycle_session import Maintenance, KUBECTL, ROOT, apps


def dns():
    address = apps.tailnet_ip('pihole-dns.tail2f646b.ts.net')
    for transport in ('+tcp', '+notcp'):
        value = apps.run(['dig', '@' + address, 'example.com', 'A', '+short', '+time=5', '+tries=2', transport])
        if not value.strip() or value.strip() == b'0.0.0.0':
            raise apps.AppError('Independent Pi-hole DNS failed')
    print('PASS: Pi-hole answers UDP and TCP DNS', flush=True)


def pending(session):
    session.off()
    value = json.loads(session.get('homelab-models', 'configmap', 'ai-scheduling-proof')['data']['pod.json'])
    session.kube('create', '-f', '-', value=value)
    session.created.append('ai-resource-filler')
    try:
        session.kube('-n', 'homelab-models', 'wait', 'pod/ai-resource-filler', '--for=condition=Ready', '--timeout=180s')
        session.command('start')
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            pods = json.loads(session.kube('-n', 'homelab-models', 'get', 'pods', '-l', 'app=ai-runtime', '-o', 'json'))['items']
            if len(pods) == 1:
                pod = pods[0]
                conditions = pod.get('status', {}).get('conditions', [])
                constrained = any(c['type'] == 'PodScheduled' and c['status'] == 'False'
                    and c.get('reason') == 'Unschedulable' and 'Insufficient cpu' in c.get('message', '') for c in conditions)
                if constrained:
                    if pod['status']['phase'] != 'Pending' or any(c.get('state', {}).get('running') for c in pod['status'].get('containerStatuses', [])):
                        raise apps.AppError('Aggregate Pod partially started despite insufficient resources')
                    break
            time.sleep(3)
        else:
            raise apps.AppError('Did not observe aggregate CPU-constrained Pending state')
        dns()
        session.command('stop')
        session.wait(lambda s: s['observed'] == 'Off', 'Stop supersedes pending Start')
    finally:
        session.remove('ai-resource-filler')


def commands(session):
    revision = session.off()
    identifier = str(uuid.uuid4())
    first = session.command('stop', revision=revision, command_id=identifier)
    second = session.command('stop', revision=revision, command_id=identifier)
    if first['acknowledged_revision'] != second['acknowledged_revision'] or session.status()['revision'] != revision + 1:
        raise apps.AppError('Repeated command was not idempotent')
    revision = session.off()
    def send(action):
        try:
            return session.command(action, revision=revision)
        except apps.AppError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, ('start', 'stop')))
    if sum(result is not None for result in results) != 1 or session.status()['revision'] != revision + 1:
        raise apps.AppError('Concurrent conflicting commands did not serialize by revision')
    session.command('stop')
    session.wait(lambda s: s['observed'] == 'Off', 'concurrent commands preserve newer Stop')


def model(session, path, payload):
    # Fixed reviewed model API destination, credentials only via curl stdin.
    config = 'header = "Authorization: Bearer ' + session.tokens['model-user'] + '"\nheader = "Content-Type: application/json"\n'
    return json.loads(apps.tailnet_https('ollama.tail2f646b.ts.net', path,
        ['--fail-with-body', '--max-time', '600', '--config', '-', '--data-binary', json.dumps(payload)], config.encode()))


def force_running(session, future):
    if future.done():
        raise apps.AppError('Force Stop proof requires a still-running inference request')
    return session.command('force-stop')


def require_interrupted(future):
    try:
        result = future.result(timeout=60)
    except apps.AppError:
        return
    if result.get('done') is True or not result.get('error'):
        raise apps.AppError('Force Stop proof failed: inference completed normally')


def models(session):
    rejected = apps.tailnet_https('ollama.tail2f646b.ts.net', '/api/tags', ['-o', '/dev/null', '-w', '%{http_code}']).decode()
    if rejected != '401':
        raise apps.AppError('Model API did not reject unauthenticated access')
    with ThreadPoolExecutor(max_workers=1) as pool:
        pull = pool.submit(model, session, '/api/pull', {'model': 'smollm2:135m', 'stream': False})
        session.wait(lambda s: s['active_work'] > 0, 'direct model download is tracked', timeout=60)
        session.command('stop')
        state = session.status()
        if state['admission'] or state['observed'] not in ('Draining', 'Stopping', 'Off'):
            raise apps.AppError('Stop did not close work admission')
        if pull.result(timeout=600).get('status') != 'success':
            raise apps.AppError('Previously admitted model download did not finish during drain')
    session.wait(lambda s: s['observed'] == 'Off', 'normal Stop drains model download')
    session.command('start')
    session.wait(lambda s: s['admission'], 'AI restarted with healthy activity sources')
    result = model(session, '/api/generate', {'model': 'smollm2:135m', 'prompt': 'Say hello.',
        'stream': False, 'options': {'num_predict': 16}})
    if result.get('done') is not True or result.get('eval_count', 0) <= 0:
        raise apps.AppError('Native private-socket inference did not complete')
    sockets = session.kube('-n', 'homelab-models', 'exec', 'deployment/ai-runtime', '-c', 'ollama', '--',
        'sh', '-c', 'for file in /tmp/homelab-native/runner-*.sock; do test -S "$file" && printf "%s\\n" "$file"; done').decode().splitlines()
    import re
    ports = [int(re.fullmatch(r'/tmp/homelab-native/runner-([0-9]+)\.sock', path).group(1)) for path in sockets]
    if not ports:
        raise apps.AppError('No native Unix socket was observed after inference')
    session.kube('-n', 'homelab-models', 'exec', 'deployment/ai-runtime', '-c', 'odysseus', '--',
        'python', '-c', """import json,pathlib,socket,sys,urllib.request,urllib.error
assert not pathlib.Path('/tmp/homelab-native').exists()
for port in json.loads(sys.argv[1]):
    with socket.socket() as connection:
        connection.settimeout(2)
        assert connection.connect_ex(('127.0.0.1', port)) != 0
try:
    urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=3)
except urllib.error.HTTPError as error:
    assert error.code == 401
else:
    raise AssertionError('unauthenticated same-Pod gateway access succeeded')
""", json.dumps(ports))
    print('PASS: authenticated native inference and rejected same-Pod socket/TCP/gateway bypass', flush=True)
    session.wait(lambda s: s['active_work'] == 0 and s['admission'], 'previous model work is fully retired')
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(model, session, '/api/generate', {'model': 'smollm2:135m',
            'prompt': ('Explain each number in this list: ' + ', '.join(map(str, range(4000)))),
            'stream': False, 'options': {'num_predict': 8192, 'num_ctx': 16384}})
        session.wait(lambda s: s['active_work'] > 0, 'direct inference is tracked before Force Stop', timeout=60)
        force_running(session, future)
        stopped = session.wait(lambda s: s['observed'] == 'Off', 'Force Stop observes bounded Pod termination', timeout=180)
        if not stopped.get('last_interruption', {}).get('tickets'):
            raise apps.AppError('Force Stop did not record interrupted work')
        require_interrupted(future)


def persistence(session):
    session.command('start')
    session.wait(lambda s: s['admission'], 'aggregate runtime ready for persistence proof')
    marker = 'acceptance-' + str(uuid.uuid4())
    paths = [('ollama', '/models'), ('odysseus', '/workspace'), ('chroma', '/data')]
    # Every write is a unique small marker, never an application reset or overwrite.
    for container, path in paths:
        command = ['sh', '-c', 'set -C; printf "%s" "$1" > "$2"', 'proof', marker, path + '/' + marker]
        session.kube('-n', 'homelab-models', 'exec', 'deployment/ai-runtime', '-c', container, '--', *command)
    session.command('stop')
    session.wait(lambda s: s['observed'] == 'Off', 'normal idle Stop completes')
    session.command('start')
    session.wait(lambda s: s['admission'], 'aggregate runtime restarted')
    for container, path in paths:
        result = session.kube('-n', 'homelab-models', 'exec', 'deployment/ai-runtime', '-c', container, '--', 'cat', path + '/' + marker)
        if result.decode() != marker:
            raise apps.AppError('Application-volume persistence mismatch')
    session.command('stop')
    session.wait(lambda s: s['observed'] == 'Off', 'three-volume persistence proof complete')


def workspace_login(session, cookie):
    bootstrap = session.get('homelab-models', 'secret', 'odysseus-bootstrap')
    password = base64.b64decode(bootstrap['data']['admin-password'], validate=True).decode()
    response = apps.tailnet_https('odysseus.tail2f646b.ts.net', '/api/auth/login',
        ['--fail-with-body', '--cookie-jar', str(cookie), '--header', 'Content-Type: application/json',
         '--data-binary', '@-'], json.dumps({'username': 'admin', 'password': password}).encode())
    if not json.loads(response).get('ok'):
        raise apps.AppError('Workspace authentication failed')
    cookie.chmod(0o600)


def workspace_idle_probes(cookie):
    # Match authenticated idle Cookbook reads and browser heartbeat, without user work.
    for path in ('/api/cookbook/state', '/api/cookbook/gpus', '/api/health'):
        apps.tailnet_https('odysseus.tail2f646b.ts.net', path,
            ['--fail-with-body', '--cookie', str(cookie)])
    apps.tailnet_https('odysseus.tail2f646b.ts.net', '/api/activity/heartbeat',
        ['--fail-with-body', '--cookie', str(cookie), '--request', 'POST'])


def recovery_idle(session):
    revision = session.off()
    session.kube('-n', 'homelab-platform', 'rollout', 'restart', 'deployment/ai-lifecycle')
    session.kube('-n', 'homelab-platform', 'rollout', 'status', 'deployment/ai-lifecycle', '--timeout=180s')
    session.wait(lambda s: s['observed'] == 'Off' and s['revision'] == revision,
                 'controller recovery preserves intentional Off', timeout=180)
    # Freshness hysteresis after recovery is intentionally not bypassed.
    session.wait(lambda s: not s['blocking_reasons'], 'storage recovery has five healthy minutes', timeout=420)
    session.command('start')
    session.wait(lambda s: s['admission'] and s['active_work'] == 0, 'verified idle interval begins')
    with tempfile.TemporaryDirectory(prefix='ai-idle-browser-') as private:
        cookie = Path(private) / 'session.cookies'
        workspace_login(session, cookie)
        start = time.monotonic()
        while time.monotonic() - start < 1780:
            state = session.status()
            if state['observed'] != 'On' or state['active_work'] or not state['admission']:
                raise apps.AppError('Continuous verified idle interval was interrupted')
            workspace_idle_probes(cookie)
            time.sleep(10)
    session.wait(lambda s: s['observed'] == 'Off' and s['reason'] == 'verified idle',
                 '30 continuous idle minutes with authenticated browser probes cause normal shutdown', timeout=180)
    dns()


def jobs(session):
    token = session.kube('-n', 'homelab-jobs', 'create', 'token', 'homelab-workflow-client', '--duration=20m').decode().strip()
    namespace = 'homelab-jobs'
    submitted = []
    cron_name = 'schedule-proof-' + uuid.uuid4().hex[:10]
    cron_created = False

    def submit(template, manual=False, parameters=None):
        value = {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Workflow',
            'metadata': {'generateName': 'maintenance-' + template + '-', 'namespace': namespace},
            'spec': {'workflowTemplateRef': {'name': template}}}
        if parameters:
            value['spec']['arguments'] = {'parameters': [{'name': key, 'value': str(item)} for key, item in parameters.items()]}
        if manual:
            result = json.loads(session.kube('--as=system:serviceaccount:homelab-jobs:homelab-workflow-client',
                                            'create', '-f', '-', '-o', 'json', value=value))
        else:
            result = session.api('/api/v1/workflows/' + namespace, {'namespace': namespace, 'workflow': value},
                                 host='argo.tail2f646b.ts.net', token=token)
        name = result['metadata']['name']
        submitted.append(name)
        return name

    def poll(names, predicate, label, timeout=240):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            values = [session.get(namespace, 'workflow', name) for name in names]
            if predicate(values):
                print('PASS: ' + label, flush=True)
                return values
            time.sleep(2)
        raise apps.AppError('Timed out: ' + label)

    def running(value):
        return any(node.get('type') == 'Pod' and node.get('phase') == 'Running'
                   for node in value.get('status', {}).get('nodes', {}).values())

    try:
        first = submit('smoke', manual=True)
        other = submit('independent-smoke')
        poll([first, other], lambda values: all(map(running, values)), 'manual and API independent jobs run concurrently')
        second = submit('smoke')
        values = poll([first, second], lambda values: running(values[0]) and bool(values[1].get('status', {}).get('synchronization')),
                      'same-job API invocation waits on shared mutex')
        if running(values[1]):
            raise apps.AppError('Same-job mutex allowed simultaneous execution')
        # Cancellation through the authorized client identity uses the Workflow API.
        session.kube('--as=system:serviceaccount:homelab-jobs:homelab-workflow-client', '-n', namespace,
                     'patch', 'workflow', second, '--type=merge', '-p', json.dumps({'spec': {'shutdown': 'Terminate'}}))
        poll([second], lambda values: values[0].get('status', {}).get('phase') in ('Failed', 'Error'),
             'queued job cancellation reaches terminal state')
        poll([first, other], lambda values: all(v.get('status', {}).get('phase') == 'Succeeded' for v in values),
             'manual and API jobs complete successfully')
        operation = submit('ai-status')
        poll([operation], lambda values: values[0].get('status', {}).get('phase') == 'Succeeded',
             'reviewed lifecycle operation executes through Argo')
        base = session.get(namespace, 'cronworkflow', 'scheduled-smoke')
        if base['spec'].get('suspend') is not True:
            raise apps.AppError('Approved smoke schedule must initially be suspended')
        # Isolated schedule instance self-stops after any terminal run, even if CI
        # is killed. The Helm-owned schedule remains suspended throughout.
        cron = {'apiVersion': base['apiVersion'], 'kind': base['kind'],
                'metadata': {'name': cron_name, 'namespace': namespace}, 'spec': base['spec']}
        cron['spec'].update(suspend=False, schedules=['* * * * *'],
            stopStrategy={'expression': 'cronworkflow.succeeded >= 1 || cronworkflow.failed >= 1'})
        session.kube('create', '-f', '-', value=cron)
        cron_created = True
        deadline = time.monotonic() + 240
        observed_active = None
        identifiers = set()
        while time.monotonic() < deadline:
            children = json.loads(session.kube('-n', namespace, 'get', 'workflows',
                '-l', 'workflows.argoproj.io/cron-workflow=' + cron_name, '-o', 'json'))['items']
            identifiers.update(v['metadata']['uid'] for v in children)
            if len(identifiers) > 1:
                raise apps.AppError('Forbid schedule created overlapping executions')
            if children and running(children[0]) and observed_active is None:
                observed_active = time.monotonic()
            if children and children[0].get('status', {}).get('phase') == 'Succeeded':
                if observed_active is None or time.monotonic() - observed_active < 60:
                    raise apps.AppError('Scheduled job did not span another schedule boundary')
                print('PASS: UTC scheduled execution, Forbid overlap and terminal completion', flush=True)
                break
            time.sleep(3)
        else:
            raise apps.AppError('Scheduled smoke did not complete')
    finally:
        if cron_created:
            session.kube('-n', namespace, 'delete', 'cronworkflow', cron_name, '--cascade=foreground', '--wait=true', '--timeout=120s')
        for name in submitted:
            session.kube('-n', namespace, 'delete', 'workflow', name, '--cascade=foreground', '--wait=true', '--timeout=120s')


def main():
    session = Maintenance()
    try:
        session.off()
        session.wait(lambda s: not s['blocking_reasons'], 'initial capacity hysteresis is healthy', timeout=420)
        jobs(session)
        pending(session)
        commands(session)
        persistence(session)
        session.command('start')
        session.wait(lambda s: s['admission'], 'AI ready for authenticated model tests')
        models(session)
        spec = importlib.util.spec_from_file_location('data_backup', ROOT / 'scripts/ai-data-backup.py')
        backup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backup)
        backup.backup_restore(session, Path(os.environ['AI_BACKUP_OUTPUT']))
        recovery_idle(session)
    finally:
        # A normal Stop is safe cleanup; unknown work is never automatically forced.
        try:
            session.command('stop')
        finally:
            session.cleanup()


if __name__ == '__main__':
    os.umask(0o077)
    def interrupted(_signal, _frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        main()
    except Exception as error:
        raise SystemExit(str(error) if isinstance(error, apps.AppError) else 'Lifecycle maintenance failed; private diagnostics suppressed') from None
