from copy import deepcopy
import json
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
from runtime import Runtime, RUNTIME, STATE, MODELS, PLATFORM
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

    def test_template_updates_are_applied_while_off_without_starting_ai(self):
        self.api.template['spec']['template']['metadata']['labels']['revision'] = 'new'
        self.api.revision = 'second'
        self.runtime.tick()
        self.assertEqual(self.api.objects[RUNTIME]['spec']['replicas'], 0)
        self.assertEqual(self.api.objects[RUNTIME]['spec']['template']['metadata']['labels']['revision'], 'new')
        self.operate('start', 0)
        self.assertEqual(self.api.objects[RUNTIME]['metadata']['annotations']['homelab/approved-revision'], 'second')

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
