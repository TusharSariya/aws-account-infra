"""No live calls: ensure bootstrap protects credentials and preview cannot apply."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class AccessTests(unittest.TestCase):
    def test_bootstrap_saves_secret_privately_without_printing_it(self):
        bootstrap = module('proxmox-provider-bootstrap')
        secret = 'test-only-secret'
        response = subprocess.CompletedProcess([], 0, json.dumps({
            'endpoint': 'https://pve.tail2f646b.ts.net/',
            'api_token': 'homelab-tofu@pve!provider=' + secret}), '')
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'credentials.json'
            output = io.StringIO()
            with patch('sys.argv', ['bootstrap', '--output', str(destination)]), \
                 patch.object(bootstrap.subprocess, 'run', return_value=response), \
                 contextlib.redirect_stdout(output):
                bootstrap.main()
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertIn(secret, destination.read_text())
            self.assertNotIn(secret, output.getvalue())
            with patch('sys.argv', ['bootstrap', '--output', str(destination)]), \
                 patch.object(bootstrap.subprocess, 'run') as remote:
                with self.assertRaises(FileExistsError):
                    bootstrap.main()
                remote.assert_not_called()

    def test_remote_error_does_not_expose_output(self):
        bootstrap = module('proxmox-provider-bootstrap')
        response = subprocess.CompletedProcess([], 1, 'test-secret-stdout', 'test-secret-stderr')
        with tempfile.TemporaryDirectory() as directory:
            with patch('sys.argv', ['bootstrap', '--output', str(Path(directory) / 'credential')]), \
                 patch.object(bootstrap.subprocess, 'run', return_value=response):
                with self.assertRaises(RuntimeError) as error:
                    bootstrap.main()
                self.assertNotIn('test-secret', str(error.exception))

    def test_plan_does_not_save_artifact_or_inherit_cli_overrides(self):
        preview = module('proxmox-tofu')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'credentials.json'
            path.write_text(json.dumps({'endpoint': 'https://pve.tail2f646b.ts.net/',
                                        'api_token': 'test-only-secret'}))
            path.chmod(0o600)
            with patch('sys.argv', ['preview', 'plan', '--credentials', str(path)]), \
                 patch.dict('os.environ', {'TF_CLI_ARGS_plan': '-out=unsafe.plan', 'TF_LOG': 'TRACE'}), \
                 patch.object(preview.subprocess, 'call', return_value=0) as command, \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    preview.main()
                self.assertEqual(result.exception.code, 0)
                argv = command.call_args.args[0]
                self.assertIn('plan', argv)
                self.assertFalse(any(arg.startswith('-out') for arg in argv))
                self.assertNotIn('test-only-secret', ' '.join(argv))
                env = command.call_args.kwargs['env']
                self.assertNotIn('TF_CLI_ARGS_plan', env)
                self.assertNotIn('TF_LOG', env)


class CIPermissionTests(unittest.TestCase):
    def setUp(self):
        self.check = module('proxmox-ci-check').check_permissions
        self.rights = {
            '/': {'Sys.Audit': 1},
            '/vms/100': {'Sys.Audit': 1},
            '/vms/102': {'VM.Audit': 1, 'VM.Config.Disk': 1},
            '/vms/101': {'Sys.Audit': 1},
            '/storage/local': {'Datastore.Audit': 1},
            '/storage/local-lvm': {'Datastore.Audit': 1},
        }

    def test_apply_rejects_missing_global_startup_permission(self):
        for path in ('/vms/102',):
            self.rights[path]['VM.Allocate'] = 1
        with self.assertRaisesRegex(ValueError, 'Sys.Modify'):
            self.check(self.rights, True)
        self.rights['/']['Sys.Modify'] = 1
        self.check(self.rights, True)

    def test_reader_rejects_global_host_modification(self):
        self.rights['/']['Sys.Modify'] = 1
        with self.assertRaises(ValueError):
            self.check(self.rights, False)

    def test_apply_allows_inherited_host_role_but_no_retired_vm_rights(self):
        self.rights['/']['Sys.Modify'] = 1
        self.rights['/vms/102']['VM.Allocate'] = 1
        self.rights['/vms/100']['Sys.Modify'] = 1
        self.check(self.rights, True)
        for privilege in ('VM.Allocate', 'VM.PowerMgmt', 'VM.Audit', 'VM.Config.Disk'):
            with self.subTest(privilege=privilege):
                self.rights['/vms/100'][privilege] = 1
                with self.assertRaisesRegex(ValueError, 'Retired VM 100'):
                    self.check(self.rights, True)
                del self.rights['/vms/100'][privilege]

    def test_limited_plan_scope(self):
        self.check(self.rights, False)
        self.rights['/vms/100']['VM.Config.CPU'] = 1
        with self.assertRaises(ValueError):
            self.check(self.rights, False)

    def test_plan_requires_existing_volume_inspection_permission(self):
        del self.rights['/vms/102']['VM.Config.Disk']
        with self.assertRaisesRegex(ValueError, 'VM.Config.Disk'):
            self.check(self.rights, False)

    def test_plan_rejects_disk_allocation(self):
        self.rights['/storage/local-lvm']['Datastore.AllocateSpace'] = 1
        with self.assertRaises(ValueError):
            self.check(self.rights, False)

    def test_apply_requires_worker_scope_and_rejects_unrelated_vm(self):
        with self.assertRaises(ValueError):
            self.check(self.rights, True)
        for path in ('/vms/102',):
            self.rights[path]['VM.Allocate'] = 1
        self.rights['/']['Sys.Modify'] = 1
        self.check(self.rights, True)
        self.rights['/vms/101']['VM.Allocate'] = 1
        with self.assertRaises(ValueError):
            self.check(self.rights, True)


if __name__ == '__main__':
    unittest.main()
