"""Verify real Helm rendering and the sleeping-worker deployment boundary."""
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
RENDER = ROOT / 'kubernetes/platform/main/placement/helm-post-renderer.py'
spec = importlib.util.spec_from_file_location('main_cluster_guard', ROOT / 'scripts/main_cluster_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class MainClusterTests(unittest.TestCase):
    def test_real_cache_chart_pins_database_and_backup_consumers(self):
        rendered = subprocess.check_output(['helm', 'template', 'homelab-cache', str(ROOT / 'charts/homelab-cache'), '--namespace', 'homelab-cache'], text=True)
        out = subprocess.check_output([str(RENDER), '--namespace', 'homelab-cache'], input=rendered, text=True)
        objects = [o for o in yaml.safe_load_all(out) if o]
        deployments = [o for o in objects if o['kind'] == 'Deployment']
        self.assertEqual({o['metadata']['name'] for o in deployments}, {'nexus', 'nexus-postgres'})
        for obj in deployments:
            pod = obj['spec']['template']['spec']
            self.assertEqual(pod['nodeSelector']['kubernetes.io/hostname'], 'talos-worker-01')
            self.assertIn('nodeAffinity', pod['affinity'])
        # Re-rendering must not accumulate preferences or change specs.
        again = subprocess.check_output([str(RENDER), '--namespace', 'homelab-cache'], input=out, text=True)
        self.assertEqual(list(yaml.safe_load_all(out)), list(yaml.safe_load_all(again)))

    def test_primary_sleep_or_cordon_blocks_apply(self):
        for ready, cordon in [('False', False), ('True', True)]:
            node = {'spec': {'unschedulable': cordon}, 'status': {'conditions': [{'type': 'Ready', 'status': ready}]}}
            with patch.object(guard.subprocess, 'check_output', return_value=json.dumps(node)):
                with self.assertRaisesRegex(ValueError, 'sleeping or cordoned'):
                    guard.require_primary_ready('kubectl')

    def test_hibernation_blocks_apply_even_after_node_returns(self):
        node = {'spec': {}, 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}
        db = {'metadata': {'annotations': {'cnpg.io/hibernation': 'on'}}}
        with patch.object(guard.subprocess, 'check_output', side_effect=[json.dumps(node), json.dumps(db)]):
            with self.assertRaisesRegex(ValueError, 'Database maintenance'):
                guard.require_primary_ready('kubectl')

    def test_ready_primary_allows_apply_and_preserves_private_environment(self):
        node = {'spec': {}, 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}
        with patch.object(guard.subprocess, 'check_output', side_effect=[json.dumps(node), json.dumps({'metadata': {}})]) as call:
            guard.require_primary_ready('kubectl', {'KUBECONFIG': '/private/config'})
            self.assertEqual(call.call_args.kwargs['env'], {'KUBECONFIG': '/private/config'})
