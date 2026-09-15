import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('expiry', Path(__file__).resolve().parents[1] / 'arc-expiry.py')
expiry = importlib.util.module_from_spec(spec); spec.loader.exec_module(expiry)


class ExpiryTests(unittest.TestCase):
    def observe(self, elapsed, job=None):
        with TemporaryDirectory() as directory:
            private = Path(directory)
            record = dict(github_created_at='2026-09-15T00:00:00Z', github_run=123,
                          blocker='owned-blocker', blocker_uid='owned-uid', candidates=['runner-uid'])
            expiry.save(private, record)
            started = expiry.datetime.fromisoformat(record['github_created_at']).timestamp()
            job = job or dict(name='expiry', status='completed', conclusion='cancelled', runner_id=0, steps=[],
                              check_run_url='https://api.github.com/repos/example/check-runs/456')
            def api(path):
                return [{'message': 'queue timeout evidence retained'}] if 'annotations' in path else {'jobs': [job]}
            with patch.object(expiry.time, 'time', return_value=started + elapsed), \
                    patch.object(expiry, 'api', side_effect=api), \
                    patch.object(expiry, 'objects', return_value=[]), \
                    patch.object(expiry, 'remove_blocker') as remove, patch('builtins.print'):
                expiry.watch(private)
            remove.assert_called_once()
            self.assertEqual(remove.call_args.args[1]['blocker_uid'], 'owned-uid')
            return json.loads((private / 'expiry-record.json').read_text())

    def test_manual_early_cancellation_is_not_expiry_and_cleans_up(self):
        result = self.observe(3600)
        self.assertEqual(result['state'], 'failed-or-interrupted')
        self.assertTrue(result['cleanup_observed'])

    def test_full_duration_still_requires_review_of_github_reason(self):
        result = self.observe(24*3600 + 60)
        self.assertEqual(result['state'], 'completed-awaiting-expiry-reason-review')
        self.assertTrue(result['annotations'])
        self.assertTrue(result['cleanup_observed'])

    def test_a_runner_acquiring_the_fixture_fails_the_proof(self):
        result = self.observe(120, dict(name='expiry', status='in_progress', runner_id=999, steps=[]))
        self.assertEqual(result['state'], 'failed-or-interrupted')
        self.assertIn('acquired a runner', result['error'])

    def test_delete_uses_uid_precondition_and_never_a_replacement(self):
        record = dict(blocker='owned', blocker_uid='owned-uid')
        with patch.object(expiry, 'objects', return_value=[{'metadata': {'uid': 'replacement'}}]), \
                patch.object(expiry, 'kubectl') as delete:
            expiry.remove_blocker(Path('/private'), record)
        delete.assert_not_called()
        with patch.object(expiry, 'objects', return_value=[{'metadata': {'uid': 'owned-uid'}}]), \
                patch.object(expiry, 'kubectl') as delete:
            expiry.remove_blocker(Path('/private'), record)
        self.assertEqual(delete.call_args.kwargs['value']['preconditions'], {'uid': 'owned-uid'})
