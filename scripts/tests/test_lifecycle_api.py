import importlib.util
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import MagicMock
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'apps/platform/lifecycle'), str(ROOT / 'apps/platform/storage')]
spec = importlib.util.spec_from_file_location('lifecycle_api', ROOT / 'apps/platform/lifecycle/server.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class APITests(unittest.TestCase):
    def setUp(self):
        self.server = api.Server(('127.0.0.1', 0), api.Handler)
        self.server.tokens = {'operator': 'operator-fixture', 'odysseus': 'workspace-fixture', 'ollama': 'model-fixture'}
        self.server.runtime = MagicMock()
        self.server.runtime.current_status.return_value = {'desired': 'off', 'observed': 'Off'}
        self.server.runtime.operate.return_value = {'observed': 'Starting/Pending'}
        self.server.runtime.activity.return_value = {'accepted': True}
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def call(self, path, key=None, payload=None):
        request = urllib.request.Request('http://127.0.0.1:' + str(self.server.server_port) + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={} if key is None else {'Authorization': 'Bearer ' + key})
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def test_operator_authentication_precedes_all_commands_and_status(self):
        for path in ('/start', '/stop', '/force-stop'):
            for key in (None, 'workspace-fixture', 'model-fixture'):
                self.assertEqual(self.call(path, key, {})[0], 401)
        self.assertEqual(self.call('/status')[0], 401)
        self.server.runtime.operate.assert_not_called()
        self.assertEqual(self.call('/start', 'operator-fixture', {})[0], 200)

    def test_activity_credentials_are_scoped_to_one_source(self):
        for path, key in [('/activity/ollama/begin', 'workspace-fixture'),
                          ('/activity/odysseus/finish', 'model-fixture'),
                          ('/activity/ollama/heartbeat', 'operator-fixture')]:
            self.assertEqual(self.call(path, key, {})[0], 401)
        self.server.runtime.activity.assert_not_called()
        self.assertEqual(self.call('/activity/ollama/heartbeat', 'model-fixture', {})[0], 200)

    def test_health_is_read_only_and_unavailable_status_fails_closed(self):
        self.assertEqual(self.call('/healthz')[0], 200)
        self.server.runtime.activity.assert_not_called()
        self.server.runtime.operate.assert_not_called()
        self.server.runtime.current_status.side_effect = api.Unavailable()
        self.assertEqual(self.call('/healthz')[0], 503)
        self.assertEqual(self.call('/status', 'operator-fixture')[0], 503)

    def test_gateway_credential_can_only_start_and_read_minimal_status(self):
        self.server.tokens['gateway'] = 'gateway-fixture'
        self.server.runtime.current_status.return_value = {'desired': 'off', 'revision': 9, 'private': 'hidden'}
        self.assertEqual(self.call('/wake-status', 'gateway-fixture'), (200, {'desired': 'off', 'revision': 9}))
        self.assertEqual(self.call('/wake', 'gateway-fixture', {'revision': 9})[0], 200)
        self.server.runtime.operate.assert_called_once_with('start', {'revision': 9})
        for path in ['/stop', '/force-stop', '/start', '/status', '/activity/ollama/begin']:
            self.assertEqual(self.call(path, 'gateway-fixture', {})[0], 401)
