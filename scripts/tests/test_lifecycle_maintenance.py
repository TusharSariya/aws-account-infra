import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('maintenance', ROOT / 'scripts/homelab-lifecycle-maintenance.py')
maintenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maintenance)


class MaintenanceTests(unittest.TestCase):
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
        self.assertIn('always()', condition)
        self.assertIn("needs.apply.result == 'success'", condition)
        self.assertIn("needs.acceptance.result == 'success'", condition)
        self.assertIn("'lifecycle-maintenance'", condition)

    def test_no_response_timeout_does_not_prove_interruption(self):
        future = Mock()
        future.result.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            maintenance.require_interrupted(future)
