from decimal import Decimal
from pathlib import Path
import subprocess
import unittest
import yaml
ROOT = Path(__file__).resolve().parents[2]


def cpu(value):
    return Decimal(value[:-1]) / 1000 if value.endswith('m') else Decimal(value)


class PackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rendered = subprocess.check_output(['helm', 'template', 'homelab-ai', str(ROOT / 'charts/homelab-ai'),
            '-f', str(ROOT / 'config/environments/kubernetes/homelab/ai-values.yaml')], text=True)
        cls.docs = [value for value in yaml.safe_load_all(rendered) if value]
        approved = next(value for value in cls.docs if value['kind'] == 'ConfigMap' and value['metadata']['name'] == 'ai-approved-template')
        cls.runtime = yaml.safe_load(approved['data']['deployment.yaml'])
        cls.pod = cls.runtime['spec']['template']['spec']

    def test_one_atomic_default_off_template_without_helm_runtime_ownership(self):
        self.assertFalse(any(d['kind'] in ('Deployment', 'StatefulSet', 'Pod', 'Job') for d in self.docs))
        self.assertEqual(self.runtime['spec']['replicas'], 0)
        self.assertEqual(self.runtime['metadata']['annotations']['homelab/desired-state'], 'off')
        containers = self.pod['containers']
        self.assertEqual({c['name'] for c in containers}, {'ollama', 'odysseus', 'chroma', 'searx'})
        self.assertEqual(sum(cpu(str(c['resources']['requests']['cpu'])) for c in containers), Decimal('35.75'))
        self.assertEqual(sum(int(c['resources']['requests']['memory'][:-2]) for c in containers), 77)
        for container in containers:
            for dimension in ('cpu', 'memory'):
                self.assertEqual(container['resources']['requests'][dimension], container['resources']['limits'][dimension])
            self.assertIn('readinessProbe', container)

    def test_retained_static_bindings_use_only_the_three_project_directories(self):
        pvs = [d for d in self.docs if d['kind'] == 'PersistentVolume']
        claims = {d['metadata']['name']: d for d in self.docs if d['kind'] == 'PersistentVolumeClaim'}
        self.assertEqual(len(pvs), 3)
        self.assertEqual({pv['spec']['local']['path'] for pv in pvs}, {
            '/var/mnt/local-path-provisioner/ai-models', '/var/mnt/local-path-provisioner/ai-workspace',
            '/var/mnt/local-path-provisioner/ai-vector'})
        for pv in pvs:
            self.assertEqual(pv['spec']['persistentVolumeReclaimPolicy'], 'Retain')
            self.assertEqual(pv['spec']['nodeAffinity']['required']['nodeSelectorTerms'][0]['matchExpressions'],
                [{'key': 'kubernetes.io/hostname', 'operator': 'In', 'values': ['talos-worker-01']}])
            claim = claims[pv['spec']['claimRef']['name']]
            self.assertEqual(claim['spec']['volumeName'], pv['metadata']['name'])
            self.assertEqual(claim['spec']['storageClassName'], '')
            self.assertEqual(claim['spec']['resources']['requests']['storage'], pv['spec']['capacity']['storage'])

    def test_user_namespace_volume_and_temporary_storage_isolation(self):
        self.assertFalse(self.pod['hostUsers'])
        self.assertFalse(self.pod['automountServiceAccountToken'])
        self.assertFalse(any('hostPath' in volume for volume in self.pod['volumes']))
        for container in self.pod['containers'] + self.pod['initContainers']:
            self.assertIn('@sha256:', container['image'])
            self.assertFalse(container['securityContext']['allowPrivilegeEscalation'])
            self.assertEqual(container['securityContext']['capabilities']['drop'], ['ALL'])
            self.assertIn('ephemeral-storage', container['resources']['limits'])
        for volume in self.pod['volumes']:
            if 'emptyDir' in volume:
                self.assertIn('sizeLimit', volume['emptyDir'])
                self.assertNotEqual(volume['emptyDir'].get('medium'), 'Memory')
        claims = {v['name'] for v in self.pod['volumes'] if 'persistentVolumeClaim' in v}
        for container in self.pod['containers']:
            owned = {m['name'] for m in container['volumeMounts']} & claims
            self.assertEqual(owned, {'ollama': {'models'}, 'odysseus': {'workspace'},
                                     'chroma': {'vector'}, 'searx': set()}[container['name']])
        env = {v['name']: v for v in self.pod['containers'][1]['env']}
        self.assertEqual(env['AUTH_ENABLED']['value'], 'true')
        self.assertEqual(env['LOCALHOST_BYPASS']['value'], 'false')


if __name__ == '__main__':
    unittest.main()
