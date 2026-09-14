"""Real certificate purpose, isolation and overwrite protection; no enrollment."""
import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('issuance', ROOT / 'scripts/issue-capacity-credentials.py')
issuance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(issuance)
host_spec = importlib.util.spec_from_file_location('host', ROOT / 'scripts/homelab-capacity-host.py')
host_module = importlib.util.module_from_spec(host_spec)
host_spec.loader.exec_module(host_module)


class IssuanceTests(unittest.TestCase):
    def test_distinct_ca_purposes_private_files_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'identities'
            issuance.issue(directory)
            host = json.loads(base64.b64decode((directory / 'host-credentials.b64').read_bytes()))
            client = json.loads(base64.b64decode((directory / 'client-credentials.b64').read_bytes()))
            self.assertEqual(set(host), {'config.json', 'server.crt', 'server.key', 'client-ca.crt'})
            self.assertEqual(set(client), {'ca.crt', 'tls.crt', 'tls.key'})
            self.assertNotEqual(host['client-ca.crt'], client['ca.crt'])
            self.assertNotEqual(host['server.key'], client['tls.key'])
            restored = directory / 'restored-ssh-key'
            host_module.write_ssh_key(restored, (directory / 'ci-host-ed25519').read_text().rstrip('\n'))
            result = subprocess.run(['ssh-keygen', '-y', '-f', str(restored)], capture_output=True)
            self.assertEqual(result.returncode, 0)
            for name in ('server-ca.key', 'client-ca.key', 'server.key', 'client.key',
                         'ci-host-ed25519', 'host-credentials.b64', 'client-credentials.b64'):
                self.assertEqual((directory / name).stat().st_mode & 0o077, 0)
            for ca, leaf, purpose in [('client-ca.crt', 'server.crt', 'sslserver'),
                                      ('server-ca.crt', 'client.crt', 'sslclient'),
                                      ('server-ca.crt', 'server.crt', 'sslclient')]:
                result = subprocess.run(['openssl', 'verify', '-CAfile', ca, '-purpose', purpose, leaf],
                                        cwd=directory, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
            original = (directory / 'client.key').read_bytes()
            with self.assertRaises(ValueError):
                issuance.issue(directory)
            self.assertEqual((directory / 'client.key').read_bytes(), original)

    def test_other_checkout_is_rejected_before_any_key_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / '.git').write_text('gitdir: fixture')
            with self.assertRaises(ValueError):
                issuance.issue(directory / 'keys')
            self.assertFalse((directory / 'keys').exists())
