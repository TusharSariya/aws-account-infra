"""Exercise fresh authenticated challenges against the actual workspace listener."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/platform/lifecycle'))
from identity import probe
from kube import Unavailable

spec = importlib.util.spec_from_file_location('workspace_identity', ROOT / 'apps/containers/odysseus/lifecycle/identity.py')
workspace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workspace)


class IdentityTests(unittest.TestCase):
    def test_authenticated_fresh_challenges_and_wrong_credential(self):
        tracker = SimpleNamespace(token='test-source-key-' * 4, process='a' * 32)
        server = workspace.serve(tracker, ('127.0.0.1', 0))
        try:
            with patch('identity.PORTS', {'odysseus': server.server_port}):
                self.assertEqual(probe('127.0.0.1', 'odysseus', tracker.token), tracker.process)
                self.assertEqual(probe('127.0.0.1', 'odysseus', tracker.token), tracker.process)
                with self.assertRaises(Unavailable):
                    probe('127.0.0.1', 'odysseus', 'wrong-source-key-' * 4)
                with self.assertRaises(Unavailable):
                    probe('127.0.0.1', 'odysseus', None)
        finally:
            server.shutdown()
            server.server_close()
        with patch('identity.PORTS', {'odysseus': server.server_port}), self.assertRaises(Unavailable):
            probe('127.0.0.1', 'odysseus', tracker.token)

    def test_replayed_signature_does_not_verify_a_new_challenge(self):
        import hashlib
        import hmac
        import io
        import json
        from unittest.mock import Mock
        key = 'test-source-key-' * 4
        old = 'a' * 32
        payload = {'process_id': 'b' * 32,
            'signature': hmac.new(key.encode(), (old + ':' + 'b' * 32).encode(), hashlib.sha256).hexdigest()}
        opener = Mock()
        opener.open.return_value = io.BytesIO(json.dumps(payload).encode())
        with patch('identity.urllib.request.build_opener', return_value=opener), patch('identity.secrets.token_hex', return_value='c' * 32):
            with self.assertRaises(Unavailable):
                probe('127.0.0.1', 'odysseus', key)
