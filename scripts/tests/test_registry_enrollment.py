import base64
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('homelab_ci_registry', ROOT/'scripts/homelab-ci.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RegistryEnrollmentTests(unittest.TestCase):
    def test_write_capable_tokens_are_rejected_before_enrollment(self):
        for scopes in ['repo, read:packages', 'read:packages, write:packages', '', 'read:packages']:
            with self.subTest(scopes=scopes), TemporaryDirectory() as temporary:
                path = Path(temporary)/'registry.json'
                path.write_text(json.dumps({'auths': {'ghcr.io': {
                    'auth': base64.b64encode(b'fixture:fixture-token').decode()}}}))
                path.chmod(0o600)
                opener = Mock()
                opener.open.return_value = nullcontext(SimpleNamespace(headers={'X-OAuth-Scopes': scopes}))
                with patch.object(module.urllib.request, 'build_opener', return_value=opener), patch.object(module, 'run') as run:
                    if scopes == 'read:packages':
                        module.enroll_registry(['kubectl'], path)
                        secret = json.loads(run.call_args.args[1])
                        self.assertEqual(secret['metadata'], {'name': 'ghcr-read', 'namespace': 'arc-runners'})
                        self.assertEqual(secret['type'], 'kubernetes.io/dockerconfigjson')
                        self.assertIn('--server-side', run.call_args.args[0])
                    else:
                        with self.assertRaisesRegex(ValueError, 'only read:packages'):
                            module.enroll_registry(['kubectl'], path)
                        run.assert_not_called()

    def test_public_credential_file_is_rejected(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary)/'registry.json'
            path.write_text('{}')
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, 'Private owned'):
                module.enroll_registry(['kubectl'], path)
