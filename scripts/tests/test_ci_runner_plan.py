import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ci_runner_plan import guard, guard_start, WORKER, RUNNER, IMAGE


class PlanTest(unittest.TestCase):
    def setUp(self):
        before = {'memory': [{'dedicated': 172 * 1024}], 'disk': [{'size': 1200}]}
        after = copy.deepcopy(before)
        after['memory'][0]['dedicated'] = 156 * 1024
        self.plan = {'variables': {'ci_runner_ssh_public_key': {'value': 'ssh-ed25519 fixture'}},
            'configuration': {'root_module': {'resources': [{'address': RUNNER.replace('[0]', ''),
                'expressions': {'disk': [{'import_from': {'references': [IMAGE + '.id', IMAGE, IMAGE.replace('[0]', '')]}}]}}]}},
            'resource_changes': [
            {'address': WORKER, 'change': {'actions': ['update'], 'before': before, 'after': after}},
            {'address': IMAGE, 'change': {'actions': ['create'], 'after': {
                'checksum': '612b2c0cc1bc413a6cb8c38fd611794caf0f2b436c50013d8b3794db12ad7354',
                'url': 'https://cloud-images.ubuntu.com/releases/noble/release-20260911/ubuntu-24.04-server-cloudimg-amd64.img',
                'content_type': 'import', 'checksum_algorithm': 'sha256', 'node_name': 'pve', 'datastore_id': 'local'}}},
            {'address': RUNNER, 'change': {'actions': ['create'], 'after': {
                'vm_id': 103, 'name': 'ci-runner-01', 'node_name': 'pve', 'started': False, 'on_boot': False,
                'initialization': [{'user_account': [{'username': 'ubuntu', 'password': None, 'keys': ['ssh-ed25519 fixture']}]}],
                'cpu': [{'cores': 4, 'limit': 4, 'sockets': 1}], 'memory': [{'dedicated': 16384, 'floating': 0}],
                'disk': [{'size': 100, 'datastore_id': 'local-lvm'}],
                'network_device': [{'bridge': 'vmbr0', 'model': 'virtio', 'mac_address': '02:42:00:00:01:05'}]}}}]}

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

    def test_early_runner_start_rejected(self):
        self.plan['resource_changes'][2]['change']['after']['started'] = True
        with self.assertRaises(ValueError):
            guard(self.plan)

    def test_extra_sockets_rejected(self):
        self.plan['resource_changes'][2]['change']['after']['cpu'][0]['sockets'] = 8
        with self.assertRaises(ValueError):
            guard(self.plan)

    def test_extra_network_rejected(self):
        self.plan['resource_changes'][2]['change']['after']['network_device'].append({'bridge': 'vmbr1'})
        with self.assertRaises(ValueError):
            guard(self.plan)

    def test_start_only(self):
        before = {'started': False, 'on_boot': False, 'memory': [{'dedicated': 16384}]}
        after = dict(before, started=True, on_boot=True)
        plan = {'resource_changes': [{'address': RUNNER, 'change': {'actions': ['update'], 'before': before, 'after': after}}]}
        self.assertEqual(guard_start(plan), [RUNNER])
        after['memory'] = [{'dedicated': 32768}]
        with self.assertRaises(ValueError):
            guard_start(plan)
