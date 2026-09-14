import base64
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location('capacity_credentials', Path(__file__).resolve().parents[1] / 'homelab-capacity-credentials.py')
credentials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(credentials)


class CredentialTests(unittest.TestCase):
    def test_pr_ref_cannot_reconcile_credentials(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/pull/67/merge'}, clear=True), \
             patch.object(credentials.subprocess, 'run') as run, self.assertRaises(ValueError):
            credentials.main()
        run.assert_not_called()

    def test_secret_is_scoped_and_removed_from_child_environment(self):
        bundle = {'ca.crt': 'test-ca', 'tls.crt': 'test-client', 'tls.key': 'test-key'}
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/heads/main', 'KUBECTL': 'kubectl',
               'CAPACITY_CLIENT_CREDENTIALS_B64': base64.b64encode(json.dumps(bundle).encode()).decode()}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(credentials.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            credentials.main()
        request = json.loads(run.call_args.kwargs['input'])
        self.assertEqual(request['metadata'], {'name': 'physical-capacity-client', 'namespace': 'homelab-platform'})
        self.assertNotIn('CAPACITY_CLIENT_CREDENTIALS_B64', run.call_args.kwargs['env'])
        self.assertIn('--server-side', run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
