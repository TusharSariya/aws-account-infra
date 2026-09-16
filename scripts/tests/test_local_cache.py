import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
import yaml
from cache_capacity import verify_cache_storage
from ci_scratch import recommend, validate_adoption

ROOT = Path(__file__).resolve().parents[2]


class ScratchTests(unittest.TestCase):
    def fixture(self):
        return [dict(cache=state, runner_id=str(i), success=True, evidence='run/'+str(i),
                     scope='whole-pod-including-images-layers-temporary-and-logs', peak_bytes=4*1024**3)
                for i, state in enumerate(['cold', 'warm', 'warm'])]

    def test_margin_rounding_and_revalidation(self):
        runs = self.fixture()
        self.assertEqual(recommend(runs), 6)
        runs[1]['peak_bytes'] += 1
        self.assertEqual(recommend(runs), 7)
        with self.assertRaises(ValueError): validate_adoption(runs, {'success': True, 'declared_gib': 6})
        self.assertEqual(validate_adoption(runs, dict(success=True, declared_gib=7, evidence='run/4', runner_id='4')), 7168)
        for run in runs: run['peak_bytes'] = 0
        self.assertEqual(recommend(runs), 2)

    def test_incomplete_or_same_runner_evidence_rejected(self):
        runs = self.fixture()
        with self.assertRaises(ValueError): recommend(runs[:2])
        runs[1]['runner_id'] = runs[0]['runner_id']
        with self.assertRaises(ValueError): recommend(runs)


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
        for p in (ROOT/'.github/workflows').glob('*.yml'):
            workflow = yaml.load(p.read_text(), Loader=yaml.BaseLoader)
            for job in workflow.get('jobs', {}).values():
                for step in job.get('steps', []):
                    action = step.get('uses','')
                    self.assertFalse(action.startswith('actions/cache@'), p.name)
                    options = step.get('with', {})
                    if action.startswith('astral-sh/setup-uv@'): self.assertEqual(options.get('enable-cache'), 'false', p.name)
                    if action.startswith('actions/setup-go@'): self.assertEqual(options.get('cache'), 'false', p.name)
                    self.assertNotIn('type=gha', str(options), p.name)


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
