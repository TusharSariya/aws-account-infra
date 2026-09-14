"""Local execution never impersonates CI and requires the recorded source/plan."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_lifecycle_record as record
import lifecycle_session


class LocalRecordTests(unittest.TestCase):
    def test_changed_source_failed_apply_and_public_record_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt.json'
            kube = Path(directory) / 'kubeconfig'
            kube.write_bytes(b'disposable'); kube.chmod(0o600)
            plan = Path(directory) / 'apps.tfplan'
            plan.write_bytes(b'guarded-plan')
            value = {'execution': 'local', 'source_tree_sha256': 'original', 'apply': 'success',
                     'plan_sha256': hashlib.sha256(plan.read_bytes()).hexdigest(),
                     'kubeconfig_sha256': hashlib.sha256(kube.read_bytes()).hexdigest()}
            path.write_text(json.dumps(value)); path.chmod(0o600)
            with patch.object(record, 'tree_digest', return_value='changed'), self.assertRaisesRegex(ValueError, 'source changed'):
                record.read_record(path, applied=True)
            with patch.object(record, 'tree_digest', return_value='original'):
                self.assertEqual(record.read_record(path, applied=True)['execution'], 'local')
                plan.write_bytes(b'changed-plan')
                with self.assertRaisesRegex(ValueError, 'saved plan changed'):
                    record.read_record(path, applied=True)
                plan.write_bytes(b'guarded-plan')
                kube.write_bytes(b'replaced')
                with self.assertRaisesRegex(ValueError, 'cluster credential identity'):
                    record.read_record(path, applied=True)
                kube.write_bytes(b'disposable')
                value['apply'] = 'pending'; path.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError, 'Successful local'):
                    record.read_record(path, applied=True)
                path.chmod(0o644)
                with self.assertRaisesRegex(ValueError, 'private'):
                    record.read_record(path)

    def test_local_maintenance_requires_record_and_explicit_confirmation(self):
        env = {'HOMELAB_LOCAL_RECEIPT': '/private/disposable/receipt.json', 'AI_MAINTENANCE_CONFIRM': 'verify-ai-lifecycle-and-restore'}
        with patch.dict(os.environ, env, clear=True), patch.object(record, 'read_record') as read, patch.object(lifecycle_session.apps, 'lifecycle_credentials', return_value={'operator': 'fixture'}):
            lifecycle_session.Maintenance()
            read.assert_called_once_with(env['HOMELAB_LOCAL_RECEIPT'], applied=True)
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(lifecycle_session.apps.AppError):
            lifecycle_session.Maintenance()

    def test_backend_overrides_and_parallel_execution_are_rejected(self):
        for env in ({'TF_WORKSPACE': 'other'}, {'TF_CLI_ARGS_plan': '-lock=false'}, {'TF_DATA_DIR': '/other'}):
            with patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
                record.guard_environment()
        with patch.dict(os.environ, {}, clear=True):
            record.guard_environment()
        with tempfile.TemporaryDirectory() as directory, patch.object(record, 'Path', side_effect=lambda _: Path(directory)):
            with record.execution_lock():
                with self.assertRaisesRegex(ValueError, 'Another local'):
                    with record.execution_lock():
                        pass

    def test_actual_workspace_and_backend_are_verified(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / '.terraform').mkdir()
            path = root / '.terraform/terraform.tfstate'
            value = {'backend': {'type': 's3', 'config': {'bucket': 'tofu-state-992382747916-us-east-1',
                'key': 'kubernetes/homelab/terraform.tfstate', 'region': 'us-east-1', 'dynamodb_table': 'tofu-locks', 'encrypt': True}}}
            path.write_text(json.dumps(value))
            record.verify_backend(root, Mock(return_value=b'default\n'))
            with self.assertRaisesRegex(ValueError, 'default'):
                record.verify_backend(root, Mock(return_value=b'other\n'))
            value['backend']['config']['key'] = 'other/state'; path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'backend differs'):
                record.verify_backend(root, Mock(return_value=b'default\n'))
