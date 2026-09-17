import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from kueue_capacity import verify_storage
from runner_catalog import CONFIG, ROOT, catalog, rendered_values, validate_rendered, validate_workflows


class CatalogTests(unittest.TestCase):
    def test_arbitrary_reviewed_size_and_odd_millicore_split(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            shutil.copy(CONFIG / 'arc-runner-values.yaml', path)
            entries = catalog()
            entries['homelab-talos-custom'] = dict(cpu=3.001, memory=5121, scratch=6145, docker=True)
            (path / 'runner-catalog.json').write_text(json.dumps(entries))
            validate_rendered(rendered_values(path), path)
            for resource, value in [('cpu', 33.501), ('memory', 153601), ('scratch', 245761), ('cpu', 0), ('cpu', .0001)]:
                invalid = copy.deepcopy(entries)
                invalid['homelab-talos-custom'][resource] = value
                (path / 'runner-catalog.json').write_text(json.dumps(invalid))
                with self.assertRaises(ValueError): catalog(path)

    def test_unknown_workflow_name_fails(self):
        with patch('runner_catalog.catalog', return_value={}):
            with self.assertRaisesRegex(ValueError, 'unknown runner'): validate_workflows()

    def test_typo_outside_catalog_prefix_and_docker_mismatch_fail(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workflows = root / '.github/workflows'
            workflows.mkdir(parents=True)
            for runner in ['typo-runner', 'homelab-talos-light']:
                selector = "${{ fromJSON('" + json.dumps({'github-hosted':'ubuntu-latest', 'talos':runner}) + "')[vars.CI_EXECUTOR] }}"
                job = {'runs-on': selector, 'steps': [{'uses':'docker/setup-buildx-action@v3'}]}
                (workflows / 'fixture.yml').write_text(json.dumps({'jobs': {'fixture': job}}))
                with patch('runner_catalog.ROOT', root), self.assertRaises(ValueError):
                    validate_workflows()

    def test_guard_accepts_catalog_entries_and_rejects_other_names_or_destroy(self):
        spec = importlib.util.spec_from_file_location('ci', ROOT / 'scripts/homelab-ci.py')
        ci = importlib.util.module_from_spec(spec); spec.loader.exec_module(ci)
        obj = dict(address='helm_release.runners["homelab-talos-light"]', change=dict(
            actions=['create'], after=dict(name='homelab-talos-light', namespace='arc-runners', version='0.14.2')))
        ci.guard(dict(resource_changes=[obj]))
        for address in ['helm_release.runners["homelab-talos-unknown"]', 'module.other.helm_release.runners']:
            invalid = copy.deepcopy(obj); invalid['address'] = address
            with self.assertRaises(ValueError): ci.guard(dict(resource_changes=[invalid]))
        obj['change']['actions'] = ['delete', 'create']
        with self.assertRaises(ValueError): ci.guard(dict(resource_changes=[obj]))


class StorageTests(unittest.TestCase):
    def fixture(self):
        fs = dict(time=datetime.now(timezone.utc).isoformat(), usedBytes=18*1024**3, availableBytes=80*1024**3)
        summary = dict(node=dict(nodeName='talos-worker-01', fs=fs, runtime=dict(imageFs=copy.deepcopy(fs))))
        node = dict(metadata=dict(name='talos-worker-01'), status=dict(allocatable={'ephemeral-storage':'88Gi','pods':'110'}))
        config = dict(scratch='60Gi', storageHeadroom='8Gi', podHeadroom=10, cpu='36', memory='160Gi')
        return node, [], summary, config, catalog()

    def test_measured_images_headroom_and_slots(self):
        args = self.fixture()
        self.assertEqual(verify_storage(*args)['runner_slots'], 30)
        for key, value in [('usedBytes', 21*1024**3), ('availableBytes', 67*1024**3), ('time', '2020-01-01T00:00:00Z')]:
            broken = copy.deepcopy(args); broken[2]['node']['runtime']['imageFs'][key] = value
            with self.assertRaises(ValueError): verify_storage(*broken)
        broken = copy.deepcopy(args); broken[0]['status']['allocatable']['pods'] = '39'
        with self.assertRaisesRegex(ValueError, 'Pod slots'): verify_storage(*broken)
        broken = copy.deepcopy(args); del broken[2]['node']['runtime']['imageFs']
        with self.assertRaises(KeyError): verify_storage(*broken)

    def test_doubled_pool_requires_expanded_disk_and_available_pod_slots(self):
        node, pods, summary, config, entries = self.fixture()
        config.update(scratch='120Gi', cpu='33.5', memory='150Gi')
        with self.assertRaises(ValueError):
            verify_storage(node, pods, summary, config, entries)
        node['status']['allocatable']['ephemeral-storage'] = '172Gi'
        for fs in (summary['node']['fs'], summary['node']['runtime']['imageFs']):
            fs['availableBytes'] = 150 * 1024**3
        self.assertEqual(verify_storage(node, pods, summary, config, entries)['runner_slots'], 33)
        node['status']['allocatable']['pods'] = '42'
        with self.assertRaisesRegex(ValueError, 'Pod slots'):
            verify_storage(node, pods, summary, config, entries)
