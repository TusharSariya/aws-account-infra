"""Secret and saved-plan boundaries across independently invoked CI steps."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import hashlib

spec = importlib.util.spec_from_file_location('ci', Path(__file__).resolve().parents[1] / 'talos-ci.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class StageTests(unittest.TestCase):
    def test_environment_overrides_and_secret_are_not_inherited(self):
        poisoned = {'TF_CLI_ARGS_plan': '-destroy', 'TF_LOG': 'TRACE', 'TOFU_LOG': 'TRACE',
                    'TF_VAR_machine_configurations': 'wrong', 'TF_DATA_DIR': '/wrong',
                    'TF_WORKSPACE': 'wrong', 'TALOS_SECRETS_B64': 'test-secret',
                    'AWS_ACCESS_KEY_ID': 'test-only', 'PATH': '/bin'}
        with patch.dict(os.environ, poisoned, clear=True):
            env = ci.clean_environment()
        self.assertEqual(env, {'AWS_ACCESS_KEY_ID': 'test-only', 'PATH': '/bin', 'AWS_PROFILE': 'admin'})

    def test_local_apply_and_changed_saved_plan_never_execute(self):
        with tempfile.TemporaryDirectory() as d:
            session = ci.Session.__new__(ci.Session)
            session.private = Path(d)
            plan = session.private / 'tfplan'
            plan.write_bytes(b'original-test-plan')
            (session.private / 'guarded-plan.sha256').write_text(hashlib.sha256(plan.read_bytes()).hexdigest())
            command = ['tofu', '-chdir=live/talos/homelab', 'apply', '-input=false', '-lock-timeout=60s', str(plan)]
            with patch.object(session, 'run') as execute:
                with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, 'GitHub CI'):
                    session.execute(command)
                with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
                    session.execute(command)
                    self.assertEqual(execute.call_count, 1)
                    plan.write_bytes(b'changed-test-plan')
                    with self.assertRaisesRegex(ValueError, 'changed after review'):
                        session.execute(command)
                    with self.assertRaisesRegex(ValueError, 'guarded saved plan'):
                        session.execute(command[:-1] + ['-auto-approve'])
                    self.assertEqual(execute.call_count, 1)

    def test_private_process_errors_do_not_disclose_output(self):
        import subprocess
        result = subprocess.CompletedProcess(['tofu'], 1, stdout='PRIVATE-CONFIG', stderr='PRIVATE-KEY')
        with patch.object(ci.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(ValueError, 'exit 1') as raised:
                ci.run_private(['tofu', 'plan'], {})
        self.assertNotIn('PRIVATE', str(raised.exception))

    def test_wrong_identity_is_rejected_before_generation(self):
        with tempfile.TemporaryDirectory() as d:
            private = Path(d)
            with patch.dict(os.environ, {'TALOS_SECRETS_B64': 'd3Jvbmc='}), patch.object(ci, 'run_private') as run:
                with self.assertRaisesRegex(ValueError, 'fingerprint'):
                    ci.prepare(private, None)
                run.assert_not_called()


class RebootBoundaryTests(unittest.TestCase):
    def test_maintenance_requires_explicit_approval_before_any_command(self):
        session = ci.Session.__new__(ci.Session)
        with patch.dict(os.environ, {}, clear=True), patch.object(session, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'explicit maintenance approval'):
                session.worker_reboot()
            run.assert_not_called()

    def test_routine_storage_signals_first_provision_without_reboot(self):
        with tempfile.TemporaryDirectory() as directory:
            session = ci.Session.__new__(ci.Session)
            session.private = Path(directory)
            session.tc = ['talosctl', '-n', 'control-plane-test-only']
            (session.private / 'storage-before.txt').write_text('blank')
            output = session.private / 'github-output'
            with patch.dict(os.environ, {'GITHUB_OUTPUT': str(output)}), \
                 patch.object(session, 'worker_resources', return_value=[]), \
                 patch.object(ci, 'check_storage_mount', return_value=True), \
                 patch.object(ci, 'guard_storage_disks', return_value='existing'), \
                 patch.object(session, 'run') as run:
                session.storage()
                self.assertTrue(all('reboot' not in call.args[0] for call in run.call_args_list))
                self.assertIn('needs_worker_reboot=true', output.read_text())

    def test_worker_auto_reboot_mode_is_rejected(self):
        plan = {'resource_changes': [{'address': 'talos_machine_configuration_apply.worker[0]',
                'change': {'actions': ['update'], 'after': {'apply_mode': 'auto'}}}]}
        with self.assertRaisesRegex(ValueError, 'must not reboot'):
            ci.guard_plan(plan)


if __name__ == '__main__':
    unittest.main()
