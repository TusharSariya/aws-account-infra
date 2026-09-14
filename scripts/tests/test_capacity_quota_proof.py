"""Reset proof freshness/fencing and separation of disposable privileged tests."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/platform/storage'))
from quota_proof import require_proof, template_revision
from workload_state import is_terminated
import live_quota
spec = importlib.util.spec_from_file_location('quota_ci', ROOT / 'scripts/quota-acceptance.py')
quota_ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quota_ci)


class ProofTests(unittest.TestCase):
    def test_retained_terminal_pods_require_every_container_to_have_exited(self):
        pod = {'spec': {'containers': [{'name': 'app'}], 'initContainers': [{'name': 'init'}],
                        'ephemeralContainers': [{'name': 'debug'}]},
               'status': {'phase': 'Succeeded', 'containerStatuses': [
                   {'name': 'app', 'state': {'terminated': {'exitCode': 0}}}]}}
        self.assertFalse(is_terminated(pod))
        for field, name in [('initContainerStatuses', 'init'), ('ephemeralContainerStatuses', 'debug')]:
            pod['status'][field] = [{'name': name, 'state': {'terminated': {'exitCode': 0}}}]
        self.assertTrue(is_terminated(pod))
        pod['status']['phase'] = 'Running'
        self.assertFalse(is_terminated(pod))
        self.assertFalse(is_terminated({}))
    def test_reset_rejects_missing_stale_changed_and_unrebooted_proof(self):
        node = {'metadata': {'uid': 'node-identity'}, 'status': {'nodeInfo': {'bootID': 'after'},
                'conditions': [{'type': 'Ready', 'status': 'True'}]}}
        record = {'phase': 'completed', 'revision': 'reviewed', 'filesystem': 'xfs-identity',
                  'node_uid': 'node-identity', 'boot_before': 'before', 'boot_after': 'after', 'completed_at': 1000}
        require_proof(record, 'reviewed', 'xfs-identity', node, 1001)
        for field, bad in [('phase', 'prepared'), ('revision', 'old'), ('filesystem', 'wrong'),
                           ('node_uid', 'replaced'), ('boot_before', 'after'), ('boot_after', 'old'),
                           ('completed_at', 1002), ('completed_at', -90000), ('completed_at', float('nan'))]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                require_proof({**record, field: bad}, 'reviewed', 'xfs-identity', node, 1001)
        self.assertNotEqual(template_revision({'admin': 'old'}), template_revision({'admin': 'new'}))

    def test_main_and_explicit_maintenance_guard_precede_all_api_calls(self):
        for env in ({}, {'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/pull/68/merge',
                         'QUOTA_ACCEPTANCE_CONFIRM': 'verify-disposable-quotas-and-reboot'}):
            with patch.dict(os.environ, env, clear=True), patch.object(subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    quota_ci.main('prepare')
                run.assert_not_called()

    def test_consumer_has_no_host_or_quota_authority_and_uses_only_disposable_claims(self):
        rendered = subprocess.check_output(['helm', 'template', 'homelab-ai', str(ROOT / 'charts/homelab-ai'),
            '-f', str(ROOT / 'config/environments/kubernetes/homelab/ai-values.yaml')], text=True)
        docs = [doc for doc in yaml.safe_load_all(rendered) if doc]
        templates = {doc['metadata']['name']: yaml.safe_load(doc['data']['job.yaml']) for doc in docs
                     if doc['kind'] == 'ConfigMap' and doc['metadata']['name'].startswith('quota-')}
        consumer = templates['quota-consumer-template']['spec']['template']['spec']
        self.assertFalse(consumer['hostUsers'])
        self.assertFalse(consumer['automountServiceAccountToken'])
        self.assertFalse(any('hostPath' in volume or 'secret' in volume for volume in consumer['volumes']))
        security = consumer['containers'][0]['securityContext']
        self.assertEqual(security['runAsUser'], 1000)
        self.assertEqual(security['capabilities'], {'drop': ['ALL']})
        claims = {v['persistentVolumeClaim']['claimName'] for v in consumer['volumes'] if 'persistentVolumeClaim' in v}
        self.assertEqual(claims, {'quota-proof-first', 'quota-proof-neighbor'})
        admin = templates['quota-admin-template']['spec']['template']['spec']
        values = yaml.safe_load((ROOT / 'config/environments/kubernetes/homelab/ai-values.yaml').read_text())
        for pod in (admin, consumer):
            self.assertEqual(pod['containers'][0]['image'], values['images']['configure'])
            self.assertRegex(pod['containers'][0]['image'], r'@sha256:[a-f0-9]{64}$')
        self.assertFalse(admin['automountServiceAccountToken'])
        self.assertEqual([v['hostPath'] for v in admin['volumes'] if 'hostPath' in v],
                         [{'path': '/var/mnt/local-path-provisioner', 'type': 'Directory'}])
        pvs = [doc for doc in docs if doc['kind'] == 'PersistentVolume' and doc['metadata']['name'].startswith('homelab-quota-proof-')]
        self.assertEqual(len(pvs), 2)
        self.assertTrue(all(pv['spec']['capacity']['storage'] == '2Mi' for pv in pvs))

    def test_administrator_accepts_actual_capacity_configuration(self):
        rendered = subprocess.check_output(['helm', 'template', 'homelab-capacity', str(ROOT / 'charts/homelab-capacity'),
            '-f', str(ROOT / 'config/environments/kubernetes/homelab/capacity-values.yaml')], text=True)
        docs = [doc for doc in yaml.safe_load_all(rendered) if doc]
        config = next(doc['data']['config.json'] for doc in docs
                      if doc['kind'] == 'ConfigMap' and doc['metadata']['name'] == 'capacity-config')
        identity = json.loads(config)['filesystemUUID']
        with patch.object(live_quota.Path, 'read_text', return_value=config), \
             patch.object(live_quota, 'open_mount', return_value=10) as mount, \
             patch.object(live_quota, 'filesystem_uuid', return_value=identity), \
             patch.object(live_quota, 'admin') as admin, patch.object(live_quota.os, 'close'):
            live_quota.main('prepare', 'a' * 32)
        mount.assert_called_once_with('/var/mnt/local-path-provisioner', '/dev/sdb1')
        admin.assert_called_once_with(10, 'prepare', 'a' * 32)

    def test_reboot_during_job_cannot_publish_prepared_evidence(self):
        saves, nodes = [], 0
        def api(command, **kwargs):
            nonlocal nodes
            if 'get' in command:
                resource, name = command[command.index('get') + 1:command.index('get') + 3]
                if resource == 'node':
                    nodes += 1
                    value = {'metadata': {'uid': 'node'}, 'status': {'nodeInfo': {'bootID': 'before' if nodes < 3 else 'after'},
                             'conditions': [{'type': 'Ready', 'status': 'True'}]}}
                elif resource == 'deployment':
                    value = {'spec': {'replicas': 0}}
                elif resource == 'pods':
                    value = {'items': []}
                elif resource == 'job':
                    value = None if '--ignore-not-found' in command else {'status': {'succeeded': 1}}
                elif name in ('guest-capacity', 'physical-capacity'):
                    value = {'data': {'sample.json': json.dumps({'fixture': {'used_percent': 1}})}}
                elif name.endswith('-template'):
                    template = {'kind': 'Job', 'metadata': {'namespace': 'homelab-platform'},
                                'spec': {'template': {'spec': {'containers': [{'command': ['python', '-B', '/code/live_quota.py']}]}}}}
                    value = {'data': {'job.yaml': yaml.safe_dump(template)}}
                elif name == 'quota-live-acceptance':
                    value = None
                else:
                    self.fail('Unexpected API read')
            else:
                value = json.loads(kwargs['input'])
                if value['kind'] == 'ConfigMap':
                    saves.append(json.loads(value['data']['proof.json'])['phase'])
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(value) if value else '')
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': 'fixture',
               'QUOTA_ACCEPTANCE_CONFIRM': 'verify-disposable-quotas-and-reboot', 'KUBECTL': 'kubectl-test'}
        with patch.dict(os.environ, env), patch.object(quota_ci, 'healthy_sample', return_value=True), \
             patch.object(quota_ci.subprocess, 'run', side_effect=api), self.assertRaisesRegex(ValueError, 'boot or readiness changed'):
            quota_ci.main('prepare')
        self.assertEqual(saves, ['preparing'])
