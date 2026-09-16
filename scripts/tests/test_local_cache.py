import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import yaml
from cache_capacity import verify_cache_storage
from ci_scratch import recommend, validate_adoption

ROOT = Path(__file__).resolve().parents[2]


class ScratchTests(unittest.TestCase):
    def fixture(self):
        return [dict(cache=state, runner_id=str(i), success=True, evidence='run/'+str(i),
                     scope='whole-pod-including-images-layers-temporary-and-logs', peak_bytes=4*1024**3,
                     coverage='before-checkout-through-cleanup', source_revision='a'*40,
                     image_digest='sha256:'+'b'*64, job='checks/test', platform='linux/amd64',
                     run_id=str(i), memory_peak_bytes=1024**3, cpu_peak_cores=1.0,
                     upstream_bytes=100, elapsed_seconds=20, cold_content_evidence='fixture-empty')
                for i, state in enumerate(['cold', 'warm', 'warm'])]

    def test_margin_rounding_and_revalidation(self):
        runs = self.fixture()
        self.assertEqual(recommend(runs), 6)
        runs[1]['peak_bytes'] += 1
        self.assertEqual(recommend(runs), 7)
        with self.assertRaises(ValueError): validate_adoption(runs, {'success': True, 'declared_gib': 6})
        self.assertEqual(validate_adoption(runs, dict(runs[0], declared_gib=7, evidence='run/4', runner_id='4', run_id='4')), 7168)
        for run in runs: run['peak_bytes'] = 0
        self.assertEqual(recommend(runs), 2)

    def test_incomplete_or_same_runner_evidence_rejected(self):
        runs = self.fixture()
        with self.assertRaises(ValueError): recommend(runs[:2])
        runs[1]['runner_id'] = runs[0]['runner_id']
        with self.assertRaises(ValueError): recommend(runs)

    def test_incomparable_or_incomplete_receipts_rejected(self):
        for field, value in [('source_revision', 'c'*40), ('image_digest', 'sha256:'+'c'*64),
                             ('job', 'other'), ('platform', 'linux/arm64'),
                             ('coverage', 'after-checkout'), ('upstream_bytes', -1),
                             ('cpu_peak_cores', float('nan'))]:
            with self.subTest(field=field):
                runs = self.fixture()
                runs[1][field] = value
                with self.assertRaises(ValueError): recommend(runs)
        runs = self.fixture()
        del runs[0]['cold_content_evidence']
        with self.assertRaises(ValueError): recommend(runs)

    def test_fourth_run_requires_comparable_complete_measurement(self):
        runs = self.fixture()
        verification = dict(runs[0], runner_id='fourth', run_id='fourth', declared_gib=6)
        self.assertEqual(validate_adoption(runs, verification), 6144)
        for field, value in [('source_revision', 'c'*40), ('peak_bytes', 6*1024**3+1),
                             ('image_digest', 'sha256:'+'c'*64), ('runner_id', '0')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_adoption(runs, dict(verification, **{field: value}))


class CacheTests(unittest.TestCase):
    def fixture(self):
        volumes = json.loads((ROOT/'config/environments/kubernetes/homelab-ci/cache-storage.json').read_text())
        def sample(identity, **extras):
            return dict(identity=identity, healthy=True, measured_at=100, used_percent=1, **extras)
        guest = {'filesystem.bytes': sample('uuid', available_bytes=1000*1024**3), 'filesystem.inodes': sample('uuid')}
        for name, volume in volumes.items():
            guest['cache.'+name] = sample(str(volume['project']), hard_limit_bytes=int(volume['size'][:-2])*1024**3)
        physical = {'pool.data': sample('pve/data', available_bytes=1500*1024**3), 'pool.metadata': sample('pve/data')}
        return guest, physical, volumes, dict(filesystemUUID='uuid', physicalPool='pve/data'), []

    def test_actual_quota_retained_volumes_and_physical_bytes(self):
        args = self.fixture()
        self.assertEqual(verify_cache_storage(*args, now=100)['cache_bytes'], str(64*1024**3))
        args[-1].append({'status': {'phase': 'Released'}, 'spec': {'capacity': {'storage': '990Gi'},
                         'local': {'path': '/var/mnt/local-path-provisioner/retained'}}})
        with self.assertRaisesRegex(ValueError, 'headroom'): verify_cache_storage(*args, now=100)
        args = self.fixture(); args[1]['pool.data']['available_bytes'] = 70*1024**3
        with self.assertRaises(ValueError): verify_cache_storage(*args, now=100)
        args = self.fixture(); args[0]['cache.blobs']['hard_limit_bytes'] = 100*1024**3
        with self.assertRaisesRegex(ValueError, 'quota'): verify_cache_storage(*args, now=100)
        with self.assertRaises(ValueError): verify_cache_storage(*self.fixture(), now=200)

    def test_chart_has_separate_bounded_services_and_no_host_mount(self):
        volumes = self.fixture()[2]
        docs = [x for x in yaml.safe_load_all(subprocess.check_output(
            ['helm', 'template', 'cache', str(ROOT/'charts/homelab-cache'), '-f', '-'],
            input=yaml.safe_dump({'volumes': volumes}).encode())) if x]
        deployments = [d for d in docs if d['kind']=='Deployment']
        self.assertEqual(len(deployments), 2)
        for d in deployments:
            spec = d['spec']['template']['spec']
            self.assertFalse(spec['automountServiceAccountToken'])
            self.assertTrue(all('hostPath' not in v for v in spec['volumes']))
            self.assertNotIn('kueue.x-k8s.io/queue-name', d['spec']['template']['metadata']['labels'])
            for c in spec['containers']:
                self.assertEqual(c['resources']['requests'], c['resources']['limits'])
                self.assertIn('@sha256:', c['image'])
        self.assertEqual(len([d for d in docs if d['kind']=='PersistentVolume']), 4)

    def test_github_dependency_cache_is_disabled(self):
        for p in (ROOT/'.github').rglob('*.yml'):
            workflow = yaml.load(p.read_text(), Loader=yaml.BaseLoader)
            groups = [j.get('steps', []) for j in workflow.get('jobs', {}).values()]
            groups.append(workflow.get('runs', {}).get('steps', []))
            for steps in groups:
                for step in steps:
                    action = step.get('uses','')
                    self.assertFalse(action.startswith(('actions/cache@', 'actions/cache/')), str(p))
                    options = step.get('with', {})
                    if action.startswith('astral-sh/setup-uv@'): self.assertEqual(options.get('enable-cache'), 'false', p.name)
                    if action.startswith('actions/setup-go@'): self.assertEqual(options.get('cache'), 'false', p.name)
                    if action.startswith(('actions/setup-node@', 'actions/setup-python@')):
                        self.assertFalse(options.get('cache'), p.name)
                    self.assertNotIn('type=gha', str(step), p.name)



class MonitorTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location('cache_monitor', ROOT/'apps/platform/cache/monitor.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_warning_boundaries_and_unavailable_telemetry(self):
        guest, _, volumes, _, _ = CacheTests().fixture()
        metrics = {'gauges': {'nexus.analytics.component_total_count': {'value': 29999},
                             'nexus.analytics.content_request_count': {'value': {'day': 74999}}}}
        evaluate = self.module().evaluate
        self.assertEqual(evaluate(guest, metrics, volumes, 100)['warnings'], [])
        guest['cache.blobs']['used_percent'] = 80
        metrics['gauges']['nexus.analytics.component_total_count']['value'] = 30000
        metrics['gauges']['nexus.analytics.content_request_count']['value']['day'] = 75000
        self.assertEqual(len(evaluate(guest, metrics, volumes, 100)['warnings']), 3)
        with self.assertRaises(ValueError): evaluate(guest, metrics, volumes, 191)
        guest['cache.blobs']['healthy'] = False
        with self.assertRaises(ValueError): evaluate(guest, metrics, volumes, 100)

    def test_monitor_has_only_metrics_secret_and_named_status_permissions(self):
        docs = [x for x in yaml.safe_load_all(subprocess.check_output(
            ['helm', 'template', 'cache', str(ROOT/'charts/homelab-cache'), '-f', '-'],
            input=yaml.safe_dump({'configure': True, 'volumes': CacheTests().fixture()[2]}).encode())) if x]
        cron = next(d for d in docs if d['kind'] == 'CronJob')
        pod = cron['spec']['jobTemplate']['spec']['template']['spec']
        secret = next(v['secret'] for v in pod['volumes'] if 'secret' in v)
        self.assertEqual(secret['items'], [{'key': 'metrics-password', 'path': 'metrics-password'}])
        for role in (d for d in docs if d['kind'] == 'Role'):
            self.assertTrue(all('secrets' not in r['resources'] for r in role['rules']))
            for rule in role['rules']:
                if rule['resources'] == ['configmaps']:
                    self.assertIn(rule['resourceNames'], [['cache-status'], ['guest-capacity']])


class ConfigurationTests(unittest.TestCase):
    def test_user_requests_match_nexus_openapi_contract(self):
        spec = importlib.util.spec_from_file_location('cache_configure', ROOT/'apps/platform/cache/configure.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        users = []
        def request(path, method='GET', value=None, **kwargs):
            if method == 'GET':
                return {'security/users?userId=admin': [], 'system/eula': {'accepted': True},
                        'blobstores/file/default': {}, 'repositories': [], 'security/roles': [],
                        'security/privileges': [], 'security/users': [{'userId': 'anonymous', 'source': 'default'}],
                        'security/realms/active': []}[path]
            if path.startswith('security/users'):
                self.assertIn('emailAddress', value)
                self.assertNotIn('email', value)
                if method == 'PUT': self.assertEqual(value['source'], 'default')
                else: self.assertIn('password', value)
                users.append(value['userId'])
        def read(path):
            return json.dumps({'acceptEula': True, 'repositories': []}) if str(path) == '/config/repositories.json' else 'fixture-password'
        with patch.object(module, 'request', side_effect=request), patch.object(module.Path, 'read_text', read):
            module.reconcile()
        self.assertEqual(users, ['anonymous', 'cache-build-writer', 'cache-monitor'])
