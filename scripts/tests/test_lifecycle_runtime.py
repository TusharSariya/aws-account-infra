from copy import deepcopy
import json
import subprocess
import yaml
import sys
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'apps/platform/lifecycle'), str(ROOT / 'apps/platform/storage')]
from capacity import Decision
from kube import Conflict, Unavailable
from leadership import LEASE_PATH
from runtime import Runtime, RUNTIME, STATE, MODELS, PLATFORM, HOLD_LEASES, TICK_BOUNDS, tick_seconds
from state import Rejected


class API:
    def __init__(self):
        self.serial = 1
        self.objects = {LEASE_PATH: {'metadata': {'resourceVersion': '1'}, 'spec': {}}}
        self.template = {'apiVersion': 'apps/v1', 'kind': 'Deployment',
            'metadata': {'name': 'ai-runtime', 'namespace': 'homelab-models', 'annotations': {}},
            'spec': {'replicas': 0, 'template': {'metadata': {'labels': {'app': 'ai-runtime'}}}}}
        self.revision = 'first'
        self.pods = []
        self.writes = []

    def call(self, method, path, value=None, optional=False):
        if path == MODELS + '/configmaps/ai-approved-template':
            return {'data': {'deployment.json': json.dumps(self.template), 'revision': self.revision}}
        if '/pods?' in path:
            return {'items': deepcopy(self.pods)}
        if path == PLATFORM + '/configmaps/ai-volume-reset-v1':
            return {'metadata': {'annotations': {'homelab/reset-phase': 'completed'}}}
        if method == 'POST':
            if RUNTIME in self.objects:
                raise Conflict()
            result = deepcopy(value)
            self.serial += 1
            result['metadata']['resourceVersion'] = str(self.serial)
            self.objects[RUNTIME] = result
            self.writes.append(deepcopy(result))
            return deepcopy(result)
        if path in self.objects:
            return deepcopy(self.objects[path])
        if optional:
            return None
        raise Unavailable()

    def put(self, path, value):
        if value['metadata']['resourceVersion'] != self.objects[path]['metadata']['resourceVersion']:
            raise Conflict()
        self.serial += 1
        result = deepcopy(value)
        result['metadata']['resourceVersion'] = str(self.serial)
        self.objects[path] = result
        self.writes.append(deepcopy(result))
        return deepcopy(result)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.api = API()
        self.runtime = Runtime(self.api, 'first-leader', {'filesystemUUID': 'filesystem', 'physicalPool': 'pool'})
        self.runtime.samples = lambda: Decision(True, False, False, ())
        self.runtime.tick()

    def operate(self, operation, revision, runtime=None):
        return (runtime or self.runtime).operate(operation, {'command_id': str(uuid.uuid4()), 'revision': revision})

    def test_rendered_parent_metadata_survives_repeated_lifecycle_commands(self):
        documents = yaml.safe_load_all(subprocess.check_output([
            'helm', 'template', 'homelab-ai', str(ROOT / 'charts/homelab-ai'),
            '-f', str(ROOT / 'config/environments/kubernetes/homelab/ai-values.yaml')]))
        approved = next(d for d in documents if d and d['kind'] == 'ConfigMap' and
                        d['metadata']['name'] == 'ai-approved-template')
        self.api.template = json.loads(approved['data']['deployment.json'])
        self.api.revision = 'kueue-parent-integration'
        def check_metadata():
            metadata = self.api.objects[RUNTIME]['spec']['template']['metadata']
            self.assertEqual(metadata['annotations']['kueue.x-k8s.io/pod-suspending-parent'], 'deployment')
            self.assertEqual(metadata['labels']['kueue.x-k8s.io/managed'], 'true')
            self.assertEqual(metadata['labels']['kueue.x-k8s.io/queue-name'], 'ai')
        self.runtime.tick()  # Off-state adoption used to erase parent integration metadata.
        check_metadata()
        for revision, operation in enumerate(['start', 'stop', 'start', 'stop']):
            self.operate(operation, revision)
            check_metadata()
            self.runtime.tick()
            check_metadata()

    def test_queue_outage_does_not_block_stop_or_status(self):
        self.runtime.config['queueStatus'] = True
        started = self.operate('start', 0)
        self.assertTrue(started['queue']['unavailable'])
        stopped = self.operate('stop', 1)
        self.assertEqual(stopped['desired'], 'off')
        self.assertEqual(self.api.objects[RUNTIME]['spec']['replicas'], 0)
        self.assertEqual(self.runtime.current_status()['desired'], 'off')

    def test_owner_hold_lease_is_read_each_tick_and_expired_or_missing_holds_are_ignored(self):
        api, runtime = self.api, self.runtime
        runtime.config['holdLease'] = 'host-hold-playground'
        lease_path = HOLD_LEASES + 'host-hold-playground'
        self.assertIsNone(runtime.hold_until())  # not rendered yet: nothing is held
        api.objects[lease_path] = {'metadata': {'resourceVersion': '9', 'labels': {'homelab.tfdraw.dev/power-hold': 'true'},
            'annotations': {'homelab.tfdraw.dev/hold-until': '2099-01-01T00:00:00+00:00'}}, 'spec': {}}
        self.assertEqual(runtime.hold_until(), '2099-01-01T00:00:00+00:00')
        api.objects[lease_path]['metadata']['annotations']['homelab.tfdraw.dev/hold-until'] = '2000-01-01T00:00:00+00:00'
        self.assertIsNone(runtime.hold_until())
        api.objects[lease_path]['metadata']['labels']['homelab.tfdraw.dev/power-hold'] = 'false'
        api.objects[lease_path]['metadata']['annotations']['homelab.tfdraw.dev/hold-until'] = '2099-01-01T00:00:00+00:00'
        self.assertIsNone(runtime.hold_until())
        runtime.tick()
        self.assertIsNone(runtime.status['hold_until'])
        api.objects[lease_path]['metadata']['labels']['homelab.tfdraw.dev/power-hold'] = 'true'
        runtime.tick()
        self.assertEqual(runtime.status['hold_until'], '2099-01-01T00:00:00+00:00')
        del runtime.config['holdLease']
        self.assertIsNone(runtime.hold_until())

    def test_pending_queue_does_not_accrue_idle_time(self):
        self.runtime.config['queueStatus'] = True
        self.operate('start', 0)
        self.api.pods = [{'metadata': {'uid': 'pending'}, 'status': {'phase': 'Pending'}}]
        self.runtime.observer.idle_since = 1
        self.runtime.tick()
        self.assertEqual(self.runtime.current_status()['idle_seconds'], 0)
        stopped = self.operate('stop', 1)
        self.assertEqual(stopped['observed'], 'Stopping')
        self.assertEqual(self.api.objects[RUNTIME]['spec']['replicas'], 0)

    def test_configured_timeout_survives_leadership_recovery(self):
        second = Runtime(self.api, 'second-leader', {**self.runtime.config, 'idleTimeoutSeconds': 300})
        second.samples = self.runtime.samples
        second.observer.idle_since = 10
        self.api.objects[LEASE_PATH]['spec']['renewTime'] = '2000-01-01T00:00:00Z'
        second.tick()
        self.assertIsNone(second.observer.idle_since)
        self.assertEqual(second.current_status()['idle_timeout_seconds'], 300)

    def test_replicas_and_desired_command_commit_in_the_same_cas(self):
        self.operate('start', 0)
        deployment = self.api.objects[RUNTIME]
        self.assertEqual(deployment['spec']['replicas'], 1)
        self.assertEqual(json.loads(deployment['metadata']['annotations'][STATE])['desired'], 'on')
        self.operate('stop', 1)
        self.assertEqual(self.api.objects[RUNTIME]['spec']['replicas'], 0)
        with self.assertRaises(Rejected):
            self.operate('start', 1)

    def test_new_leader_fences_old_controller_and_resets_idle_continuity(self):
        second = Runtime(self.api, 'second-leader', self.runtime.config)
        second.samples = self.runtime.samples
        self.assertFalse(second.acquire())
        self.runtime.observer.idle_since = 0
        self.api.objects[LEASE_PATH]['spec']['renewTime'] = '2000-01-01T00:00:00Z'
        second.tick()
        self.assertIsNone(second.observer.idle_since)
        with self.assertRaises(Conflict):
            self.operate('start', 0)
        self.operate('start', 0, second)
        state = json.loads(self.api.objects[RUNTIME]['metadata']['annotations'][STATE])
        self.assertEqual(state['owner'], 'second-leader')
        self.assertEqual(state['desired'], 'on')

    def test_stale_resource_version_cannot_undo_new_command(self):
        stale = deepcopy(self.api.objects[RUNTIME])
        self.operate('start', 0)
        with self.assertRaises(Conflict):
            self.api.put(RUNTIME, stale)
        self.assertEqual(self.api.objects[RUNTIME]['spec']['replicas'], 1)

    def test_steady_state_tick_reads_but_never_rewrites_the_runtime(self):
        def runtime_writes():
            return sum(1 for value in self.api.writes if value['metadata'].get('name') == 'ai-runtime')
        written = runtime_writes()
        for _ in range(5):
            self.runtime.tick()
        # Only the Lease renewal is written per tick; the Deployment is untouched.
        self.assertEqual(runtime_writes(), written)
        self.assertEqual(self.runtime.current_status()['desired'], 'off')
        # A real change still commits in one write.
        self.operate('start', 0)
        self.assertEqual(runtime_writes(), written + 1)
        self.assertEqual(self.api.objects[RUNTIME]['spec']['replicas'], 1)

    def test_tick_cadence_is_bounded_under_the_heartbeat_gap(self):
        self.assertEqual(tick_seconds({}), 10)
        self.assertEqual(tick_seconds({'tickSeconds': TICK_BOUNDS[0]}), TICK_BOUNDS[0])
        for invalid in (1, TICK_BOUNDS[1] + 1, 10.0, '10', True):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                tick_seconds({'tickSeconds': invalid})
        runtime = Runtime(self.api, 'cadence', {**self.runtime.config, 'tickSeconds': 5})
        self.assertEqual(runtime.tick_seconds, 5)

    def test_template_updates_are_applied_while_off_without_starting_ai(self):
        self.api.template['spec']['template']['metadata']['labels']['revision'] = 'new'
        self.api.revision = 'second'
        self.runtime.tick()
        self.assertEqual(self.api.objects[RUNTIME]['spec']['replicas'], 0)
        self.assertEqual(self.api.objects[RUNTIME]['spec']['template']['metadata']['labels']['revision'], 'new')
        self.operate('start', 0)
        self.assertEqual(self.api.objects[RUNTIME]['metadata']['annotations']['homelab/approved-revision'], 'second')

    def conflicting_status_write(self, mutate=None):
        original = self.api.put
        injected = False
        def put(path, value):
            nonlocal injected
            if path == RUNTIME and not injected:
                injected = True
                self.api.serial += 1
                current = self.api.objects[RUNTIME]
                current['metadata']['resourceVersion'] = str(self.api.serial)
                current['status'] = {'observedGeneration': 1}
                current['metadata']['managedFields'] = [{'manager': 'kube-controller-manager'}]
                if mutate:
                    mutate(current)
            return original(path, value)
        return patch.object(self.api, 'put', side_effect=put)

    def test_status_only_conflict_preserves_verified_idle_and_admission(self):
        self.running_sources()
        before = self.runtime.observer.idle_since
        with self.conflicting_status_write():
            self.runtime.tick()
        self.assertEqual(self.runtime.observer.idle_since, before)
        self.assertTrue(self.runtime.current_status()['admission'])

    def test_status_only_conflict_commits_command_and_replicas_together(self):
        with self.conflicting_status_write():
            self.operate('start', 0)
        saved = self.api.objects[RUNTIME]
        self.assertEqual(saved['spec']['replicas'], 1)
        self.assertEqual(json.loads(saved['metadata']['annotations'][STATE])['revision'], 1)

    def test_conflict_retry_rejects_changed_runtime_intent_or_identity(self):
        for field in ('spec', 'annotations', 'uid', 'generation', 'deletionTimestamp'):
            with self.subTest(field=field):
                self.setUp()
                def mutate(current):
                    if field == 'spec':
                        current['spec']['replicas'] = 9
                    elif field == 'annotations':
                        current['metadata']['annotations'][STATE] = '{}'
                    else:
                        current['metadata'][field] = 'changed'
                with self.conflicting_status_write(mutate), self.assertRaises(Conflict):
                    self.operate('start', 0)

    def test_status_conflict_retry_rechecks_leadership(self):
        def expire(_current):
            self.runtime.leader.valid_until = 0
        with self.conflicting_status_write(expire), self.assertRaises(Unavailable):
            self.operate('start', 0)
        self.assertEqual(self.api.objects[RUNTIME]['spec']['replicas'], 0)

    def test_status_conflict_retry_is_bounded(self):
        original = self.api.put
        attempts = []
        def put(path, value):
            if path == RUNTIME:
                attempts.append(value)
                self.api.serial += 1
                self.api.objects[RUNTIME]['metadata']['resourceVersion'] = str(self.api.serial)
            return original(path, value)
        with patch.object(self.api, 'put', side_effect=put), self.assertRaises(Conflict):
            self.operate('start', 0)
        self.assertEqual(len(attempts), 2)

    def test_api_read_failure_is_not_evidence_of_pod_termination(self):
        self.operate('start', 0)
        previous = deepcopy(self.api.objects[RUNTIME])
        with patch.object(self.api, 'call', side_effect=Unavailable()), self.assertRaises(Unavailable):
            self.runtime.tick()
        self.assertEqual(self.api.objects[RUNTIME], previous)

    def test_capacity_sources_cannot_replace_each_others_measurements(self):
        runtime = Runtime(self.api, 'collector-reader', self.runtime.config)
        guest = {'filesystem.bytes': {'identity': 'guest'}, 'pool.data': {'identity': 'forged-pool'}}
        physical = {'pool.data': {'identity': 'physical'}, 'filesystem.bytes': {'identity': 'forged-guest'}}
        self.api.objects[PLATFORM + '/configmaps/guest-capacity'] = {'data': {'sample.json': json.dumps(guest)}}
        self.api.objects[PLATFORM + '/configmaps/physical-capacity'] = {'data': {'sample.json': json.dumps(physical)}}
        with patch.object(runtime.capacity, 'evaluate') as evaluate:
            runtime.samples()
            self.assertEqual(evaluate.call_args.args[0], {
                'filesystem.bytes': {'identity': 'guest'}, 'pool.data': {'identity': 'physical'}})
        del self.api.objects[PLATFORM + '/configmaps/guest-capacity']
        with patch.object(runtime.capacity, 'evaluate') as evaluate:
            runtime.samples()
            self.assertNotIn('filesystem.bytes', evaluate.call_args.args[0])

    def running_sources(self):
        self.operate('start', 0)
        self.processes = {'ollama': 'a' * 32, 'odysseus': 'b' * 32}
        self.runtime.probe = lambda address, source, key: self.processes[source]
        self.api.pods = [{'metadata': {'uid': 'pod-one'}, 'status': {
            'phase': 'Running', 'podIP': '10.0.0.1',
            'conditions': [{'type': 'Ready', 'status': 'True'}],
            'containerStatuses': [{'name': source, 'containerID': source + '-one',
                                   'state': {'running': {}}} for source in self.processes]}}]
        for source in self.processes:
            self.runtime.activity(source, 'heartbeat', self.payload(source, tickets=[], known=True))
        self.assertTrue(self.runtime.current_status()['admission'])

    def payload(self, source, **values):
        return {'pod_uid': 'pod-one', 'process_id': self.processes[source], **values}

    def start_work(self):
        import time
        self.runtime.activity('ollama', 'begin', self.payload('ollama', ticket='c' * 32, deadline=time.time() + 25))

    def test_old_process_messages_are_rejected_after_same_pod_container_restart(self):
        self.running_sources()
        self.start_work()
        stale = self.payload('ollama', ticket='c' * 32, tickets=['c' * 32], known=True)
        self.processes['ollama'] = 'd' * 32
        self.api.pods[0]['status']['containerStatuses'][0]['containerID'] = 'ollama-two'
        for operation in ('begin', 'finish', 'heartbeat'):
            with self.subTest(operation=operation), self.assertRaises(Rejected):
                self.runtime.activity('ollama', operation, stale)
        self.assertEqual(self.runtime.current_status()['active_work'], 1)

    def test_only_observed_old_container_termination_retires_its_work(self):
        self.running_sources()
        self.start_work()
        self.operate('stop', 1)
        container = self.api.pods[0]['status']['containerStatuses'][0]
        self.processes['ollama'] = 'd' * 32
        container['containerID'] = 'ollama-two'
        self.runtime.tick()
        self.assertEqual(self.runtime.current_status()['active_work'], 1)
        self.assertEqual(self.api.objects[RUNTIME]['spec']['replicas'], 1)
        container['lastState'] = {'terminated': {'containerID': 'ollama-one', 'exitCode': 137}}
        self.runtime.tick()
        self.assertEqual(self.runtime.current_status()['active_work'], 0)
        # New process remains unverified until its own heartbeat arrives.
        self.assertEqual(self.api.objects[RUNTIME]['spec']['replicas'], 1)
        self.runtime.activity('ollama', 'heartbeat', self.payload('ollama', tickets=[], known=True))
        self.assertEqual(self.api.objects[RUNTIME]['spec']['replicas'], 0)
        self.assertEqual(self.runtime.current_status()['observed'], 'Stopping')
        self.assertEqual(self.runtime.current_status()['last_interruption']['tickets'], {'c' * 32: 'ollama'})

    def test_changed_process_with_stale_container_status_blocks_admission(self):
        self.running_sources()
        self.processes['ollama'] = 'd' * 32
        with self.assertRaises(Rejected):
            self.start_work()
        self.runtime.tick()
        self.assertFalse(self.runtime.current_status()['admission'])
        self.assertIn('ollama: activity unverified', self.runtime.current_status()['blocking_reasons'])

    def test_begin_checks_heartbeat_freshness_before_next_tick(self):
        import time
        self.running_sources()
        self.assertTrue(self.runtime.status['admission'])
        with patch('runtime.time.time', return_value=time.time() + 16), self.assertRaises(Rejected):
            self.start_work()
        self.assertEqual(json.loads(self.api.objects[RUNTIME]['metadata']['annotations'][STATE])['tickets'], {})

    def test_activity_uses_one_verified_process_snapshot(self):
        from unittest.mock import Mock
        self.running_sources()
        self.runtime.probe = Mock(side_effect=lambda address, source, key: self.processes[source])
        self.start_work()
        self.assertEqual(self.runtime.probe.call_count, 2)

    def test_failed_identity_probe_blocks_graceful_drain_and_idle(self):
        self.running_sources()
        with patch.object(self.runtime, 'probe', side_effect=Unavailable()):
            self.runtime.tick()
            self.assertFalse(self.runtime.current_status()['admission'])
            self.assertIsNone(self.runtime.observer.idle_since)
            self.operate('stop', 1)
        self.assertEqual(self.api.objects[RUNTIME]['spec']['replicas'], 1)
        self.assertEqual(self.runtime.current_status()['observed'], 'Draining')
