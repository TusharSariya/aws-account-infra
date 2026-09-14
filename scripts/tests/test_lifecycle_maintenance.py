import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('maintenance', ROOT / 'scripts/homelab-lifecycle-maintenance.py')
maintenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maintenance)


class MaintenanceTests(unittest.TestCase):
    def test_short_idle_acceptance_detects_late_timer_reset(self):
        session = Mock()
        session.status.side_effect = [
            {'idle_timeout_seconds': 60},
            {'observed': 'On', 'reason': 'start', 'active_work': 0, 'admission': True, 'idle_seconds': 50},
            {'observed': 'On', 'reason': 'start', 'active_work': 0, 'admission': True, 'idle_seconds': 0}]
        with patch.object(maintenance.yaml, 'safe_load', return_value={'config': {'idleTimeoutSeconds': 60}}), \
                patch.object(maintenance, 'workspace_login'), patch.object(maintenance, 'workspace_idle_probes'), \
                patch.object(maintenance.time, 'sleep'), \
                self.assertRaisesRegex(maintenance.apps.AppError, 'idle interval was interrupted'):
            maintenance.recovery_idle(session)

    def test_idle_acceptance_rejects_unexpected_deployed_timeout(self):
        session = Mock()
        session.status.return_value = {'idle_timeout_seconds': 1800}
        with self.assertRaisesRegex(maintenance.apps.AppError, 'differs from reviewed configuration'):
            maintenance.recovery_idle(session)

    def test_cancelled_storage_cleanup_rejects_replacement_namespace_before_mutation(self):
        session = Mock()
        session.kube.return_value = b'{"metadata":{"uid":"replacement"}}'
        with self.assertRaisesRegex(maintenance.apps.AppError, 'namespace identity changed'):
            maintenance.cleanup_cancelled_storage_fixture(session)
        self.assertEqual(session.kube.call_count, 1)
        self.assertEqual(session.kube.call_args.args[0], 'get')

    def test_cancelled_storage_cleanup_is_noop_after_fixture_is_gone(self):
        session = Mock()
        session.kube.side_effect = [b'', b'{"items":[]}']
        maintenance.cleanup_cancelled_storage_fixture(session)
        self.assertTrue(all(call.args[0] == 'get' for call in session.kube.call_args_list))

    def test_lifecycle_retry_preserves_command_and_does_not_retry_semantic_conflict(self):
        import lifecycle_session
        session = lifecycle_session.Maintenance.__new__(lifecycle_session.Maintenance)
        session.tokens = {'operator': 'disposable-test-token'}
        payload = {'revision': 7, 'command_id': '420a154c-350e-429c-87ee-7317ca995728'}
        replies = [b'{"error":"State changed; retry the same command ID and revision"}\n409',
                   b'{"error":"temporary observation failure"}\n503', b'{"acknowledged_revision":8}\n200']
        with patch.object(lifecycle_session.apps, 'tailnet_ip', return_value='100.101.182.1') as resolve, patch.object(lifecycle_session.apps, 'tailnet_https', side_effect=replies) as request, patch.object(lifecycle_session.time, 'sleep'):
            self.assertEqual(session.api('/stop', payload)['acknowledged_revision'], 8)
            resolve.assert_called_once()
            self.assertEqual(request.call_args_list[0], request.call_args_list[1])
            self.assertEqual(request.call_args_list[1], request.call_args_list[2])
        with patch.object(lifecycle_session.apps, 'tailnet_ip', return_value='100.101.182.1'), patch.object(lifecycle_session.apps, 'tailnet_https', return_value=b'{"error":"Command revision changed"}\n409') as request:
            with self.assertRaisesRegex(maintenance.apps.AppError, 'HTTP 409'):
                session.api('/stop', payload)
            self.assertEqual(request.call_count, 1)
        with patch.object(lifecycle_session.apps, 'tailnet_https', side_effect=maintenance.apps.AppError('ambiguous submission')) as request:
            with self.assertRaises(maintenance.apps.AppError):
                session.api('/api/v1/workflows/homelab-jobs', {}, host='argo.tail2f646b.ts.net')
            self.assertEqual(request.call_count, 1)

    def test_missing_peer_consumes_only_request_deadline_without_curl(self):
        import lifecycle_session
        session = lifecycle_session.Maintenance.__new__(lifecycle_session.Maintenance)
        session.tokens = {'operator': 'disposable-test-token'}
        now = [100.0]
        def sleep(seconds):
            now[0] += seconds
        with patch.object(lifecycle_session.time, 'monotonic', side_effect=lambda: now[0]), patch.object(lifecycle_session.time, 'sleep', side_effect=sleep), patch.object(lifecycle_session.apps, 'run', return_value=b'{"Peer":{}}') as run, patch.object(lifecycle_session.apps, 'tailnet_https') as request:
            with self.assertRaisesRegex(maintenance.apps.AppError, 'discovery deadline'):
                session.api('/status')
            self.assertEqual(now[0], 130)
            self.assertEqual(run.call_count, 6)
            self.assertTrue(all(call.kwargs['timeout'] <= 5 for call in run.call_args_list))
            request.assert_not_called()

    def test_workspace_login_keeps_password_out_of_command_arguments(self):
        import base64
        import json
        import tempfile
        session = Mock()
        session.get.return_value = {'data': {'admin-password': base64.b64encode(b'disposable-test-password').decode()}}
        with tempfile.TemporaryDirectory() as directory:
            cookie = Path(directory) / 'cookie'
            cookie.touch()
            with patch.object(maintenance.apps, 'tailnet_https', return_value=b'{"ok":true}') as request:
                maintenance.workspace_login(session, cookie)
                arguments = request.call_args.args
                self.assertNotIn('disposable-test-password', repr(arguments[:3]))
                self.assertEqual(json.loads(arguments[3])['password'], 'disposable-test-password')
                self.assertEqual(cookie.stat().st_mode & 0o777, 0o600)

    def test_graceful_stop_requires_observed_active_drain(self):
        future, session = Mock(), Mock()
        future.done.return_value = True
        with self.assertRaisesRegex(maintenance.apps.AppError, 'still-running'):
            maintenance.stop_running(session, future)
        session.command.assert_not_called()
        future.done.return_value = False
        for state in ({'admission': False, 'observed': 'Off', 'active_work': 0},
                      {'admission': False, 'observed': 'Stopping', 'active_work': 0},
                      {'admission': False, 'observed': 'Draining', 'active_work': 0},
                      {'admission': True, 'observed': 'Draining', 'active_work': 1}):
            session.status.return_value = state
            with self.assertRaisesRegex(maintenance.apps.AppError, 'observed active Draining'):
                maintenance.stop_running(session, future)
        session.status.return_value = {'admission': False, 'observed': 'Draining', 'active_work': 1}
        maintenance.stop_running(session, future)
        future.done.side_effect = [False, True]
        with self.assertRaisesRegex(maintenance.apps.AppError, 'observed active Draining'):
            maintenance.stop_running(session, future)

    def test_normal_completion_before_force_stop_is_not_interruption_proof(self):
        future = Mock()
        future.result.return_value = {'done': True, 'response': 'finished'}
        with self.assertRaisesRegex(maintenance.apps.AppError, 'completed normally'):
            maintenance.require_interrupted(future)
        future.result.side_effect = maintenance.apps.AppError('transport terminated')
        maintenance.require_interrupted(future)

    def test_already_failed_request_cannot_be_used_as_force_stop_proof(self):
        future = Mock()
        future.done.return_value = True
        future.result.side_effect = maintenance.apps.AppError('failed before command')
        session = Mock()
        with self.assertRaisesRegex(maintenance.apps.AppError, 'still-running'):
            maintenance.force_running(session, future)
        session.command.assert_not_called()

    def test_explicit_maintenance_is_not_suppressed_by_skipped_reboot_ancestor(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/tofu-apply.yml').read_text())
        condition = workflow['jobs']['lifecycle-maintenance']['if']
        self.assertIn('!cancelled()', condition)
        self.assertNotIn('always()', condition)
        self.assertIn("needs.apply.result == 'success'", condition)
        self.assertIn("needs.acceptance.result == 'success'", condition)
        self.assertIn("'lifecycle-maintenance'", condition)

    def test_no_response_timeout_does_not_prove_interruption(self):
        future = Mock()
        future.result.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            maintenance.require_interrupted(future)
