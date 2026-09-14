import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import homelab_fixture


class FixtureTests(unittest.TestCase):
    def test_discovery_timeout_does_not_remove_strict_server_validation(self):
        value = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': 'storage-check-test'}}
        def transport(command, **kwargs):
            if '--raw' not in command:
                raise TimeoutError('OpenAPI discovery unavailable')
            self.assertIn('/api/v1/namespaces?fieldValidation=Strict&dryRun=All', command)
            self.assertEqual(json.loads(kwargs['input']), value)
            return Mock(returncode=0)
        with patch.object(homelab_fixture.subprocess, 'run', side_effect=transport):
            self.assertEqual(homelab_fixture.create('kubectl', value, dry_run=True).returncode, 0)

    def test_fixture_cannot_target_application_namespace(self):
        value = {'apiVersion': 'v1', 'kind': 'Pod',
                 'metadata': {'name': 'test', 'namespace': 'homelab-models'}}
        with patch.object(homelab_fixture.subprocess, 'run') as run, self.assertRaises(ValueError):
            homelab_fixture.create('kubectl', value)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
