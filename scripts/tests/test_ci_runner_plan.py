import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ci_runner_plan import guard, WORKER, RUNNER, IMAGE


class PlanTest(unittest.TestCase):
    def setUp(self):
        before = {'memory': [{'dedicated': 172 * 1024}], 'disk': [{'size': 1200}]}
        after = copy.deepcopy(before)
        after['memory'][0]['dedicated'] = 156 * 1024
        self.plan = {'resource_changes': [
            {'address': WORKER, 'change': {'actions': ['update'], 'before': before, 'after': after}},
            {'address': IMAGE, 'change': {'actions': ['create'], 'after': {
                'checksum': '612b2c0cc1bc413a6cb8c38fd611794caf0f2b436c50013d8b3794db12ad7354',
                'checksum_algorithm': 'sha256', 'node_name': 'pve', 'datastore_id': 'local'}}},
            {'address': RUNNER, 'change': {'actions': ['create'], 'after': {
                'vm_id': 103, 'name': 'ci-runner-01', 'node_name': 'pve',
                'cpu': [{'cores': 4, 'limit': 4}], 'memory': [{'dedicated': 16384, 'floating': 0}],
                'disk': [{'size': 100, 'datastore_id': 'local-lvm'}],
                'network_device': [{'mac_address': '02:42:00:00:01:03'}]}}}]}

    def test_exact_activation(self):
        self.assertEqual(set(guard(self.plan)), {WORKER, RUNNER, IMAGE})

    def test_worker_disk_change_rejected(self):
        self.plan['resource_changes'][0]['change']['after']['disk'][0]['size'] = 1300
        with self.assertRaises(ValueError):
            guard(self.plan)

    def test_replacement_rejected(self):
        self.plan['resource_changes'][1]['change']['actions'] = ['delete', 'create']
        with self.assertRaises(ValueError):
            guard(self.plan)

    def test_missing_resize_rejected(self):
        self.plan['resource_changes'].pop(0)
        with self.assertRaises(ValueError):
            guard(self.plan)

    def test_unrelated_mutation_rejected(self):
        self.plan['resource_changes'].append({'address': 'unexpected', 'change': {'actions': ['update']}})
        with self.assertRaises(ValueError):
            guard(self.plan)

    def test_wrong_identity_rejected(self):
        self.plan['resource_changes'][2]['change']['after']['vm_id'] = 100
        with self.assertRaises(ValueError):
            guard(self.plan)
