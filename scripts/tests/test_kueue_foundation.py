import copy
import unittest
from kueue_capacity import requests, verify
from ci_retirement_plan import guard, guard_ai_off
from ci_runner_plan import WORKER, RUNNER, IMAGE


class CapacityTests(unittest.TestCase):
    def test_restartable_init_budget(self):
        def c(cpu, **kw):
            return dict(resources={'requests': {'cpu': cpu}}, **kw)
        pod = {'spec': {'containers': [c('2')], 'initContainers': [c('1', restartPolicy='Always'), c('4')]}}
        self.assertEqual(requests(pod, 'cpu'), 5)

    def test_observed_restored_worker_capacity(self):
        node = {'metadata': {'name': 'talos-worker-01'}, 'status': {
            'conditions': [{'type': 'Ready', 'status': 'True'}], 'capacity': {'memory': '115288768Ki'},
            'allocatable': {'cpu': '37950m', 'memory': '114793152Ki'}}}
        verify(node, [], {'cpu': '6', 'memory': '24Gi'})
        self.assertEqual(verify(node, [], {'cpu': '6', 'memory': '26Gi'})['cpu']['pool'], '37.950')
        with self.assertRaisesRegex(ValueError, 'allocatable'):
            verify(node, [], {'cpu': '6', 'memory': '24Gi'}, {'cpu': '31.5', 'memory': '144Gi'})

    def test_pool_and_platform_must_fit(self):
        node = {'metadata': {'name': 'talos-worker-01'}, 'status': {
            'conditions': [{'type': 'Ready', 'status': 'True'}], 'capacity': {'memory': '112Gi'},
            'allocatable': {'cpu': '37950m', 'memory': '109Gi'}}}
        verify(node, [], {'cpu': '6.5', 'memory': '25Gi'})
        service = {'metadata': {}, 'spec': {'nodeName': 'talos-worker-01', 'containers': [{'resources': {'requests': {'cpu':'38'}}}]}}
        with self.assertRaisesRegex(ValueError, 'allocatable'):
            verify(node, [service], {'cpu': '6.8', 'memory': '25Gi'})
        node['status']['capacity']['memory'] = '100Gi'
        with self.assertRaisesRegex(ValueError, 'capacity'):
            verify(node, [], {'cpu': '1', 'memory': '1Gi'})


class RetirementTests(unittest.TestCase):
    def test_retirement_requires_observed_ai_off(self):
        deployment = {'metadata': {'namespace': 'homelab-models', 'name': 'ai-runtime',
                        'annotations': {'homelab/desired-state': 'off'}}, 'spec': {'replicas': 0}}
        guard_ai_off(deployment, {'items': []})
        with self.assertRaisesRegex(ValueError, 'AI Off'):
            guard_ai_off(deployment, {'items': [{'metadata': {'name': 'terminating'}}]})
        deployment['spec']['replicas'] = 1
        with self.assertRaisesRegex(ValueError, 'AI Off'):
            guard_ai_off(deployment, {'items': []})

    def plan(self):
        worker = dict(vm_id=102, name='talos-worker-01', node_name='pve', memory=[{'dedicated': 156*1024}])
        after = copy.deepcopy(worker); after['memory'][0]['dedicated'] = 172*1024
        runner = dict(vm_id=103, name='ci-runner-01', node_name='pve', started=False, on_boot=False,
                      network_device=[{'mac_address': '02:42:00:00:01:05'}], disk=[{'size': 100, 'datastore_id': 'local-lvm'}])
        image = dict(node_name='pve', datastore_id='local', file_name='ci-ubuntu-24.04-20260911.qcow2',
                     checksum='612b2c0cc1bc413a6cb8c38fd611794caf0f2b436c50013d8b3794db12ad7354')
        return {'resource_changes': [dict(address=a, change=dict(actions=[action], before=b, after=c))
                                    for a, action, b, c in [(WORKER,'update',worker,after),(RUNNER,'delete',runner,None),(IMAGE,'delete',image,None)]]}

    def test_only_exact_retirement(self):
        self.assertEqual(set(guard(self.plan())), {WORKER, RUNNER, IMAGE})
        for address in ['vm_id', 'started', 'name']:
            plan = self.plan(); plan['resource_changes'][1]['change']['before'][address] = 'wrong'
            with self.assertRaises(ValueError): guard(plan)
        plan = self.plan(); plan['resource_changes'][0]['change']['after']['disk'] = []
        with self.assertRaises(ValueError): guard(plan)
        plan = self.plan(); plan['resource_changes'].pop()
        with self.assertRaises(ValueError): guard(plan)
