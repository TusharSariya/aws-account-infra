import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]


class CapacityChartTests(unittest.TestCase):
    def render(self, enabled=False):
        values = {'enabled': enabled, 'config': {
            'filesystemUUID': '1a6eb2f2-3217-4821-b595-e572153623fa',
            'physicalURL': 'https://100.101.182.9:9443/capacity', 'physicalPool': 'pve/data'},
            'physicalAddress': '100.101.182.9/32',
            'code': {f.name: f.read_text() for f in (ROOT / 'apps/platform/storage').glob('*.py')}}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as file:
            json.dump(values, file)
            file.flush()
            result = subprocess.check_output(['helm', 'template', 'homelab-capacity',
                str(ROOT / 'charts/homelab-capacity'), '-f', file.name], text=True)
        return [doc for doc in yaml.safe_load_all(result) if doc]

    def test_not_enrolled_does_not_run_helpers_or_mutate_application_volumes(self):
        docs = self.render()
        self.assertFalse(any(doc['kind'] in ('Deployment', 'Job', 'PersistentVolume', 'PersistentVolumeClaim') for doc in docs))
        states = [doc['data']['sample.json'] for doc in docs if doc['kind'] == 'ConfigMap' and doc['metadata']['name'].endswith('-capacity')]
        self.assertEqual(states, ['{}', '{}'])

    def test_only_guest_helper_has_filesystem_privileges(self):
        docs = self.render(True)
        pods = {d['metadata']['name']: d['spec']['template']['spec'] for d in docs if d['kind'] == 'Deployment'}
        self.assertEqual(set(pods), {'guest-capacity', 'physical-capacity'})
        guest, physical = pods['guest-capacity'], pods['physical-capacity']
        self.assertIn('SYS_ADMIN', guest['containers'][0]['securityContext']['capabilities']['add'])
        self.assertNotIn('add', physical['containers'][0]['securityContext']['capabilities'])
        self.assertTrue(physical['containers'][0]['securityContext']['runAsNonRoot'])
        for pod in pods.values():
            probe = pod['containers'][0]['readinessProbe']
            self.assertIn('exec', probe)
            self.assertIsNone(probe['exec'])
            self.assertEqual(probe['httpGet'], {'path': '/ready', 'port': 'health'})
            self.assertNotIn('hostPID', pod)
            self.assertNotIn('hostNetwork', pod)
        self.assertFalse(any('secret' in volume for volume in guest['volumes']))
        self.assertFalse(any('hostPath' in volume for volume in physical['volumes']))
        self.assertEqual([v['secret']['secretName'] for v in physical['volumes'] if 'secret' in v], ['physical-capacity-client'])

    def test_service_accounts_cannot_change_each_others_evidence(self):
        for doc in self.render(True):
            if doc['kind'] == 'Role':
                self.assertEqual(doc['rules'], [{'apiGroups': [''], 'resources': ['configmaps'],
                    'resourceNames': [doc['metadata']['name']], 'verbs': ['patch']}])

    def test_activation_rejects_unenrolled_filesystem(self):
        result = subprocess.run(['helm', 'template', 'capacity', str(ROOT/'charts/homelab-capacity'),
                                 '--set', 'enabled=true'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('filesystem UUID', result.stderr)


if __name__ == '__main__':
    unittest.main()
