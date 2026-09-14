"""Serialize desired state, tracking and replicas in one resource-version write."""
from copy import deepcopy
import json
import threading
import time

from capacity import CapacityGate
from collector import PROJECTS
from kube import Conflict, Unavailable
from leadership import Leadership
from state import Observation, Rejected, initial, command, begin, finish, heartbeat
from workload_state import is_terminated
from identity import probe

PLATFORM = '/api/v1/namespaces/homelab-platform'
MODELS = '/api/v1/namespaces/homelab-models'
DEPLOYMENTS = '/apis/apps/v1/namespaces/homelab-models/deployments'
RUNTIME = DEPLOYMENTS + '/ai-runtime'
STATE = 'homelab/lifecycle-state'


class Runtime:
    def __init__(self, api, identity, config, source_keys=None):
        self.api, self.identity, self.config = api, identity, config
        self.source_keys = source_keys or {}
        self.probe = probe
        self.leader = Leadership(api, identity)
        self.lock = threading.RLock()
        self.observer = Observation()
        self.capacity = self.new_capacity_gate()
        self.status = None
        self.status_at = 0
        self.last_alert = None

    def new_capacity_gate(self):
        return CapacityGate({**{name: str(project) for name, (_, project, _) in PROJECTS.items()},
            'filesystem.bytes': self.config['filesystemUUID'], 'filesystem.inodes': self.config['filesystemUUID'],
            'pool.data': self.config['physicalPool'], 'pool.metadata': self.config['physicalPool']})

    def samples(self):
        samples = {}
        for source in ('guest', 'physical'):
            try:
                obj = self.api.call('GET', PLATFORM + '/configmaps/' + source + '-capacity')
                measured = json.loads(obj['data']['sample.json'])
                allowed = ({'pool.data', 'pool.metadata'} if source == 'physical'
                           else set(PROJECTS) | {'filesystem.bytes', 'filesystem.inodes'})
                if isinstance(measured, dict):
                    samples.update({name: measured[name] for name in allowed if name in measured})
            except (Unavailable, KeyError, ValueError, TypeError):
                pass  # Missing input is evaluated as unhealthy, never cached as fresh.
        return self.capacity.evaluate(samples, wall_time=time.time(), monotonic_time=time.monotonic())

    def approved(self):
        obj = self.api.call('GET', MODELS + '/configmaps/ai-approved-template')
        value = json.loads(obj['data']['deployment.json'])
        if (value['metadata']['name'] != 'ai-runtime' or value['metadata']['namespace'] != 'homelab-models'
                or value['spec']['replicas'] != 0):
            raise Unavailable('Approved runtime template is invalid')
        return value, obj['data']['revision']

    def read(self):
        approved, revision = self.approved()
        obj = self.api.call('GET', RUNTIME, optional=True)
        if obj is None:
            if not self.leader.active():
                raise Unavailable('Lifecycle leadership unavailable')
            state = initial()
            state['owner'] = self.identity
            obj = deepcopy(approved)
            obj['metadata'].setdefault('annotations', {}).update({STATE: json.dumps(state), 'homelab/approved-revision': revision})
            obj = self.api.call('POST', DEPLOYMENTS + '?fieldValidation=Strict', obj)
        state = json.loads(obj['metadata']['annotations'][STATE])
        pods = self.api.call('GET', MODELS + '/pods?labelSelector=app%3Dai-runtime')['items']
        self.retire_observed_work(state, pods)
        active = [pod for pod in pods if not is_terminated(pod)]
        return obj, state, active, approved, revision

    def retire_observed_work(self, state, pods):
        by_uid = {pod['metadata']['uid']: pod for pod in pods}
        def terminated(instance):
            parts = instance.split('|')
            if len(parts) != 3:
                return False
            uid, container_id, _ = parts
            if uid not in by_uid:
                return True  # Successful Pod listing observed the former Pod absent.
            for container in by_uid[uid].get('status', {}).get('containerStatuses', []):
                for field in ('state', 'lastState'):
                    result = container.get(field, {}).get('terminated', {})
                    identifier = result.get('containerID')
                    if field == 'state' and result:
                        identifier = identifier or container.get('containerID')
                    if identifier == container_id and type(result.get('exitCode')) is int:
                        return True
            return False
        retired = {key: value['source'] for key, value in state['tickets'].items() if terminated(value['instance'])}
        for ticket in retired:
            del state['tickets'][ticket]
        state['sources'] = {key: value for key, value in state['sources'].items() if not terminated(value['instance'])}
        if retired:
            state['interruption'] = {'revision': state['revision'], 'reason': 'observed container termination', 'tickets': retired}
            self.observer.idle_since = None

    def persist(self, obj, state, replicas=None):
        self.leader.fence(obj, state)
        value = deepcopy(obj)
        value.pop('status', None)
        value['metadata']['annotations'][STATE] = json.dumps(state, separators=(',', ':'))
        value['metadata']['annotations']['homelab/desired-state'] = state['desired']
        value['metadata']['annotations']['homelab/command-revision'] = str(state['revision'])
        if replicas is not None:
            value['spec']['replicas'] = replicas
        # Deployment status reconciliation can race with an unchanged command.
        # Retry once only when every field of the observed intent is identical.
        try:
            return self.api.put(RUNTIME, value)
        except Conflict:
            current = self.api.call('GET', RUNTIME)
            def intent(resource):
                result = deepcopy(resource)
                result.pop('status', None)
                for field in ('resourceVersion', 'managedFields'):
                    result['metadata'].pop(field, None)
                return result
            if intent(current) != intent(obj):
                raise
            self.leader.fence(current, state)
            value['metadata']['resourceVersion'] = current['metadata']['resourceVersion']
            if 'managedFields' in current['metadata']:
                value['metadata']['managedFields'] = current['metadata']['managedFields']
            else:
                value['metadata'].pop('managedFields', None)
            return self.api.put(RUNTIME, value)

    def acquire(self):
        if not self.leader.renew():
            self.status = None
            return False
        obj, state, _, _, _ = self.read()
        if state['owner'] != self.identity:
            state['owner'] = self.identity
            # This CAS fences any older leader's pending runtime write.
            self.persist(obj, state)
            self.observer = Observation()
            self.capacity = self.new_capacity_gate()
        return True

    def observations(self, pods, state):
        ready = len(pods) == 1 and not pods[0]['metadata'].get('deletionTimestamp') and any(
            condition.get('type') == 'Ready' and condition.get('status') == 'True'
            for condition in pods[0].get('status', {}).get('conditions', []))
        instances = {}
        for pod in pods:
            for container in pod.get('status', {}).get('containerStatuses', []):
                source = container['name']
                if source in ('ollama', 'odysseus') and container.get('state', {}).get('running') is not None:
                    try:
                        container_id = container['containerID']
                        process = self.probe(pod['status']['podIP'], source, self.source_keys.get(source))
                        prior = state['sources'].get(source, {}).get('instance', '').split('|')
                        # A new listener with unchanged container status is ambiguous.
                        # Wait for Kubernetes to observe the actual replacement.
                        if len(prior) == 3 and prior[:2] == [pod['metadata']['uid'], container_id] and prior[2] != process:
                            continue
                        instances[source] = '|'.join((pod['metadata']['uid'], container_id, process))
                    except (Unavailable, KeyError, ValueError):
                        continue
        unstarted = bool(pods) and all(
            not any(c.get('state', {}).get('running') or c.get('state', {}).get('terminated') or c.get('lastState')
                    for c in pod.get('status', {}).get('containerStatuses', []))
            and pod.get('status', {}).get('phase') == 'Pending' for pod in pods)
        return bool(ready), instances, unstarted

    def evaluate(self, obj, state, pods, approved, revision, capacity, observed=None):
        ready, instances, unstarted = observed if observed is not None else self.observations(pods, state)
        state, replicas, status = self.observer.reconcile(state, now=time.monotonic(), wall_time=time.time(), capacity=capacity,
            pods_present=bool(pods), ready=ready, instances=instances, unstarted=unstarted)
        if not pods and state['desired'] == 'off':
            obj['spec'] = deepcopy(approved['spec'])
            obj['metadata']['annotations']['homelab/approved-revision'] = revision
        elif obj['metadata']['annotations'].get('homelab/approved-revision') != revision:
            status['blocking_reasons'].append('Approved template update waits for AI to be off')
        return obj, state, replicas, status

    def alert(self, obj, status):
        warning = status['storage_warning']
        if warning == self.last_alert:
            return
        if warning:
            event = {'apiVersion': 'v1', 'kind': 'Event',
                'metadata': {'generateName': 'ai-storage-pressure-', 'namespace': 'homelab-models'},
                'involvedObject': {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'name': 'ai-runtime',
                                   'namespace': 'homelab-models', 'uid': obj['metadata']['uid']},
                'type': 'Warning', 'reason': 'StorageCapacityPressure',
                'message': 'Storage warning or unavailable telemetry; inspect authenticated lifecycle Status.',
                'source': {'component': 'ai-lifecycle'}}
            self.api.call('POST', MODELS + '/events?fieldValidation=Strict', event)
        self.last_alert = warning

    def tick(self):
        with self.lock:
            if not self.acquire():
                return
            obj, state, pods, approved, revision = self.read()
            obj, state, replicas, status = self.evaluate(obj, state, pods, approved, revision, self.samples())
            saved = self.persist(obj, state, replicas)
            self.status, self.status_at = status, time.monotonic()
            self.alert(saved, status)

    def current_status(self):
        with self.lock:
            if not self.leader.active() or self.status is None or time.monotonic() - self.status_at > 10:
                raise Unavailable('Verified lifecycle Status is temporarily unavailable')
            return deepcopy(self.status)

    def operate(self, action, payload):
        with self.lock:
            obj, state, pods, approved, revision = self.read()
            self.leader.fence(obj, state)
            capacity = self.samples()
            if action == 'start':
                receipt = self.api.call('GET', PLATFORM + '/configmaps/ai-volume-reset-v1', optional=True)
                if not receipt or receipt['metadata'].get('annotations', {}).get('homelab/reset-phase') != 'completed':
                    raise Rejected('The one-time AI volume migration is not complete')
                if pods and obj['metadata']['annotations'].get('homelab/approved-revision') != revision:
                    raise Rejected('Stop AI before adopting the approved template update')
            if not pods and state['desired'] == 'off':
                obj['spec'] = deepcopy(approved['spec'])
                obj['metadata']['annotations']['homelab/approved-revision'] = revision
            state, acknowledged = command(state, action, payload.get('command_id'), payload.get('revision'), capacity)
            obj, state, replicas, status = self.evaluate(obj, state, pods, approved, revision, capacity)
            self.persist(obj, state, replicas)
            self.status, self.status_at = status, time.monotonic()
            return {**status, 'acknowledged_revision': acknowledged}

    def activity(self, source, operation, payload):
        with self.lock:
            obj, state, pods, approved, revision = self.read()
            self.leader.fence(obj, state)
            observed = self.observations(pods, state)
            ready, instances, _ = observed
            instance = instances.get(source)
            if (not instance or instance.split('|')[0] != payload.get('pod_uid')
                    or instance.split('|')[2] != payload.get('process_id')):
                raise Rejected('Activity source is not the observed running AI container')
            capacity = self.samples()
            obj, state, replicas, verified = self.evaluate(obj, state, pods, approved, revision, capacity, observed)
            if operation == 'heartbeat':
                state = heartbeat(state, source, instance, payload.get('tickets', []), payload.get('known'), time.time())
            elif operation == 'begin':
                state = begin(state, source, instance, payload.get('ticket'), payload.get('parent'), capacity,
                              ready and verified['admission'],
                              now=time.time(), deadline=payload.get('deadline'))
            elif operation == 'finish':
                state = finish(state, source, instance, payload.get('ticket'), now=time.time())
            else:
                raise Rejected('Unknown activity operation')
            obj, state, replicas, status = self.evaluate(obj, state, pods, approved, revision, capacity, observed)
            self.persist(obj, state, replicas)
            self.status, self.status_at = status, time.monotonic()
            return {'accepted': True, 'desired': state['desired'], 'force': state['force'], 'admission': status['admission']}
