import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('ai_images', ROOT / 'scripts/verify-ai-images.py')
images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(images)


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = Path(self.directory.name)
        self.records = {name: {'image': name + '@sha256:' + 'a' * 64, 'input_sha256': 'fixture',
                              'run_id': 1, 'artifact_id': 2, 'commit': 'a' * 40} for name in ('ollama', 'odysseus')}
        (self.config / 'ai-image-releases.json').write_text(json.dumps(self.records))
        self.refs = {name: record['image'] for name, record in self.records.items()}

    def test_changed_source_or_digest_cannot_reuse_successful_build(self):
        with patch.object(images, 'CONFIG', self.config), patch.object(images, 'input_hash', return_value='changed'), self.assertRaises(images.ImageError):
            images.verify(self.refs)
        with patch.object(images, 'CONFIG', self.config), patch.object(images, 'input_hash', return_value='fixture'), self.assertRaises(images.ImageError):
            images.verify({**self.refs, 'ollama': 'different-digest'})

    def test_unsuccessful_or_wrong_commit_build_blocks_deployment(self):
        for conclusion in ('failure', 'cancelled', 'skipped', None):
            value = {'status': 'completed', 'conclusion': conclusion, 'head_sha': 'a' * 40,
                     'path': '.github/workflows/ollama-image.yml'}
            with patch.object(images, 'CONFIG', self.config), patch.object(images, 'input_hash', return_value='fixture'), \
                 patch.dict(images.os.environ, {'GH_TOKEN': 'disposable-test-only'}), \
                 patch.object(images.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(value).encode())), \
                 self.assertRaises(images.ImageError):
                images.verify(self.refs, remote=True)
        value.update(conclusion='success', head_sha='b' * 40)
        with patch.object(images, 'CONFIG', self.config), patch.object(images, 'input_hash', return_value='fixture'), \
             patch.dict(images.os.environ, {'GH_TOKEN': 'disposable-test-only'}), \
             patch.object(images.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(value).encode())), \
             self.assertRaises(images.ImageError):
            images.verify(self.refs, remote=True)

    def remote_fixture(self, name):
        record = self.records[name]
        return [{'status': 'completed', 'conclusion': 'success', 'head_sha': record['commit'],
                 'path': '.github/workflows/' + name + '-image.yml'},
                {'id': 2, 'expired': False, 'name': name + '-image-receipt',
                 'workflow_run': {'id': 1, 'head_sha': record['commit']}}]

    def test_exact_successful_build_and_input_pair_pass(self):
        responses = self.remote_fixture('ollama') + self.remote_fixture('odysseus')
        receipts = [{k: r[k] for k in ('image', 'commit', 'run_id', 'input_sha256')}
                    for r in self.records.values()]
        with patch.object(images, 'CONFIG', self.config), patch.object(images, 'input_hash', return_value='fixture'), \
             patch.dict(images.os.environ, {'GH_TOKEN': 'disposable-test-only'}), \
             patch.object(images, 'api_json', side_effect=responses), \
             patch.object(images, 'artifact_receipt', side_effect=receipts):
            images.verify(self.refs, remote=True)

    def test_updating_local_hash_cannot_reuse_old_successful_image(self):
        old_receipt = {k: self.records['ollama'][k] for k in ('image', 'commit', 'run_id', 'input_sha256')}
        self.records['ollama']['input_sha256'] = 'changed'
        (self.config / 'ai-image-releases.json').write_text(json.dumps(self.records))
        with patch.object(images, 'CONFIG', self.config), patch.object(images, 'input_hash', return_value='changed'), \
             patch.dict(images.os.environ, {'GH_TOKEN': 'disposable-test-only'}), \
             patch.object(images, 'api_json', side_effect=self.remote_fixture('ollama')), \
             patch.object(images, 'artifact_receipt', return_value=old_receipt), \
             self.assertRaisesRegex(images.ImageError, 'do not match'):
            images.verify(self.refs, remote=True)

    def test_expired_or_other_run_receipt_is_rejected(self):
        for field, value in [('expired', True), ('workflow_run', {'id': 9, 'head_sha': 'a' * 40})]:
            responses = self.remote_fixture('ollama')
            responses[1][field] = value
            with patch.object(images, 'api_json', side_effect=responses), self.assertRaises(images.ImageError):
                images.verify_remote('ollama', self.records['ollama'], 'disposable-test-only')

    def test_signed_download_receives_no_github_credential_and_checks_archive(self):
        import hashlib
        import urllib.error
        import zipfile
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('receipt.json', '{"verified": true}')
        payload = archive.getvalue()
        artifact = {'id': 2, 'digest': 'sha256:' + hashlib.sha256(payload).hexdigest()}
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError('https://api.github.com', 302, 'redirect',
            {'Location': 'https://storage.example/receipt'}, None)
        with patch.object(images.urllib.request, 'build_opener', return_value=opener), \
             patch.object(images.urllib.request, 'urlopen', return_value=io.BytesIO(payload)) as download:
            self.assertEqual(images.artifact_receipt(artifact, 'disposable-test-only'), {'verified': True})
            download.assert_called_once_with('https://storage.example/receipt', timeout=30)
            self.assertEqual(opener.open.call_args.args[0].get_header('Authorization'), 'Bearer disposable-test-only')
        artifact['digest'] = 'sha256:' + '0' * 64
        with patch.object(images.urllib.request, 'build_opener', return_value=opener), \
             patch.object(images.urllib.request, 'urlopen', return_value=io.BytesIO(payload)), \
             self.assertRaisesRegex(images.ImageError, 'checksum'):
            images.artifact_receipt(artifact, 'disposable-test-only')
