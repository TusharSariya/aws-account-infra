"""Fail-closed deployment and rendered service contracts; no credentials required."""
import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('apps', ROOT / 'scripts/homelab-apps.py')
apps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apps)


class GuardTests(unittest.TestCase):
    def plan(self, action):
        return {'resource_changes': [{'address': a, 'change': {'actions': action}} for a in apps.ADDRESSES]}

    def test_safe_plan_and_forbidden_resource_actions(self):
        for actions in [['create'], ['update'], ['no-op']]:
            self.assertEqual(len(apps.guard_plan(self.plan(actions))), 2)
        for actions in [['delete'], ['delete', 'create'], ['forget']]:
            with self.assertRaises(apps.AppError):
                apps.guard_plan(self.plan(actions))
        invalid = self.plan(['create'])
        invalid['resource_changes'][0]['address'] = 'talos_machine_bootstrap.cluster'
        with self.assertRaises(apps.AppError):
            apps.guard_plan(invalid)
        with self.assertRaises(apps.AppError):
            apps.guard_plan({'resource_changes': []})

    def test_missing_credentials_prevent_any_cluster_mutation(self):
        with patch.dict(apps.os.environ, {'GITHUB_ACTIONS': 'true', **dict.fromkeys(apps.SECRET_NAMES, '')}), patch.object(apps, 'run') as run:
            with self.assertRaises(apps.AppError):
                apps.bootstrap('kubectl')
            run.assert_not_called()

    def test_changed_saved_plan_cannot_apply(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(apps.os.environ, {'GITHUB_ACTIONS': 'true'}), patch.object(apps, 'run') as run:
            p = Path(d)
            (p / 'apps.tfplan').write_bytes(b'changed')
            (p / 'apps-plan.sha256').write_text('previous')
            with self.assertRaises(apps.AppError):
                apps.execute('apply', p)
            run.assert_not_called()

    def test_raw_and_encoded_credentials_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'kubeconfig').write_text('users: []\n')
            with patch.dict(apps.os.environ, {'PIHOLE_ADMIN_PASSWORD': 'fixture-password-only'}):
                for value in ['fixture-password-only', base64.b64encode(b'fixture-password-only').decode()]:
                    with self.assertRaises(apps.AppError):
                        apps.check_secrets(json.dumps({'value': value}).encode(), p)

    def test_child_environment_excludes_credentials(self):
        with patch.dict(apps.os.environ, dict.fromkeys(apps.SECRET_NAMES, 'fixture')), patch.object(apps.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b''
            apps.run(['command'])
            for name in apps.SECRET_NAMES:
                self.assertNotIn(name, run.call_args.kwargs['env'])


class ChartTests(unittest.TestCase):
    def render(self, name, version, namespace, values):
        data = subprocess.check_output(['helm', 'template', name,
            str(apps.TF / '.terraform' / f'{name}-{version}.tgz'), '-n', namespace,
            '-f', str(apps.CONFIG / values)], text=True)
        return [x for x in yaml.safe_load_all(data) if x]

    def test_pihole_ports_storage_auth_and_update_contract(self):
        docs = self.render('pihole', '2.38.0', 'homelab-services', 'pihole-values.yaml')
        by_kind = {}
        for doc in docs:
            by_kind.setdefault(doc['kind'], []).append(doc)
        self.assertNotIn('Secret', by_kind)
        deployment = by_kind['Deployment'][0]['spec']
        self.assertEqual(deployment['replicas'], 1)
        self.assertEqual(deployment['strategy']['type'], 'Recreate')
        pod = deployment['template']['spec']
        self.assertEqual(pod['dnsPolicy'], 'None')
        self.assertEqual(pod['dnsConfig']['nameservers'], ['1.1.1.1', '1.0.0.1'])
        self.assertFalse(pod['hostNetwork'])
        container = pod['containers'][0]
        self.assertIn('@sha256:', container['image'])
        env = {x['name']: x for x in container['env']}
        self.assertEqual(env['FTLCONF_webserver_api_password']['valueFrom']['secretKeyRef']['name'], 'pihole-admin')
        self.assertEqual(env['FTLCONF_database_maxDBdays']['value'], '7')
        services = by_kind['Service']
        self.assertTrue(all(x['spec']['type'] == 'ClusterIP' for x in services))
        dns = next(x for x in services if x['metadata']['name'] == 'pihole-dns')
        self.assertEqual({(x['port'], x['protocol']) for x in dns['spec']['ports']}, {(53, 'TCP'), (53, 'UDP')})
        self.assertEqual(dns['metadata']['annotations']['tailscale.com/expose'], 'true')
        self.assertFalse(any(p['port'] == 67 for s in services for p in s['spec']['ports']))
        pvc = by_kind['PersistentVolumeClaim'][0]
        self.assertEqual(pvc['spec']['storageClassName'], 'worker-local-retain')
        self.assertEqual(pvc['metadata']['annotations']['helm.sh/resource-policy'], 'keep')
        ingress = by_kind['Ingress'][0]
        self.assertEqual(ingress['spec']['ingressClassName'], 'tailscale')
        self.assertNotIn('tailscale.com/funnel', ingress['metadata'].get('annotations', {}))

    def test_operator_uses_external_secret_and_pinned_images(self):
        docs = self.render('tailscale-operator', '1.102.3', 'tailscale', 'operator-values.yaml')
        self.assertFalse(any(d['kind'] == 'Secret' for d in docs))
        dep = next(d for d in docs if d['kind'] == 'Deployment')
        pod = dep['spec']['template']['spec']
        self.assertTrue(any(v.get('secret', {}).get('secretName') == 'operator-oauth' for v in pod['volumes']))
        self.assertIn('@sha256:', pod['containers'][0]['image'])


if __name__ == '__main__':
    unittest.main()
