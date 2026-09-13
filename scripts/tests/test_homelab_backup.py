"""Recovery contracts: archive compatibility and fail-closed publication."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('backup', Path(__file__).resolve().parents[1] / 'homelab-backup.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class BackupTests(unittest.TestCase):
    def test_snapshot_corruption(self):
        body = b'database'
        b.verify_snapshot(body + hashlib.sha256(body).digest())
        with self.assertRaises(b.BackupError):
            b.verify_snapshot(body + bytes(32))

    def test_receipts_old_and_new(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt'
            for value in [json.dumps({'bucket': b.BUCKET, 'key': b.KEY, 'version_id': 'v1'}),
                          f's3://{b.BUCKET}/bootstrap/old.age\nVersion: v1\nPASS: restored\n']:
                path.write_text(value)
                self.assertEqual(b.read_receipt(path)['version_id'], 'v1')
            for version in ['', 'null']:
                path.write_text(json.dumps({'bucket': b.BUCKET, 'key': b.KEY, 'version_id': version}))
                with self.assertRaises(b.BackupError):
                    b.read_receipt(path)

    def archive(self, directory, files):
        packed = Path(directory) / 'test.tar.gz'
        with tarfile.open(packed, 'w:gz') as archive:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return packed

    def test_all_existing_archive_layouts(self):
        body = b'snapshot'
        snapshot = body + hashlib.sha256(body).digest()
        metadata = {'snapshot_sha256': hashlib.sha256(snapshot).hexdigest(), 'snapshot_status': {'revision': 7}}
        with tempfile.TemporaryDirectory() as directory, patch.object(b, 'verify_identity'), patch.object(b, 'etcdutl', return_value='etcdutl'), patch.object(b, 'run', return_value=b'{"revision":7}'):
            for prefix, expected in [('homelab/', 'etcd-homelab-v1'), ('./', 'etcd-dot-v1')]:
                packed = self.archive(directory, {prefix + 'etcd.snapshot': snapshot,
                    prefix + 'talos-secrets.yaml': b'identity', prefix + 'snapshot-metadata.json': json.dumps(metadata).encode()})
                self.assertEqual(b.inspect_archive(packed, Path(directory))['archive_format'], expected)
            packed = self.archive(directory, dict.fromkeys(b.BOOTSTRAP_FILES, b'original'))
            self.assertEqual(b.inspect_archive(packed, Path(directory))['archive_format'], 'bootstrap-home-v1')

    def test_unsafe_archive_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            packed = self.archive(directory, {'../escape': b'bad'})
            with self.assertRaises(b.BackupError):
                b.inspect_archive(packed, Path(directory))

    def test_upload_reads_exact_version_and_compares_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            encrypted = Path(directory) / 'backup.age'
            encrypted.write_bytes(b'ciphertext')
            calls = []
            def aws(command):
                calls.append(command)
                if 'put-object' in command:
                    return b'{"VersionId":"exact-version"}'
                Path(command[-1]).write_bytes(b'ciphertext')
                return b'{}'
            with patch.object(b, 'run', side_effect=aws):
                receipt = b.upload_verified(['aws'], encrypted, b.KEY, {})
            self.assertEqual(receipt['version_id'], 'exact-version')
            self.assertIn('--version-id', calls[1])
            self.assertIn('exact-version', calls[1])
            with patch.object(b, 'run', return_value=b'{"VersionId":"null"}'):
                with self.assertRaises(b.BackupError):
                    b.upload_verified(['aws'], encrypted, b.KEY, {})
            def corrupt(command):
                if 'put-object' in command:
                    return b'{"VersionId":"v1"}'
                Path(command[-1]).write_bytes(b'corrupt')
                return b'{}'
            with patch.object(b, 'run', side_effect=corrupt):
                with self.assertRaises(b.BackupError):
                    b.upload_verified(['aws'], encrypted, b.KEY, {})

    def test_failed_capture_cannot_publish_or_heartbeat(self):
        with patch.dict(b.os.environ, {'GITHUB_ACTIONS': 'true', 'TALOS_SECRETS_B64': 'aWQ='}), patch.object(b, 'aws_command', return_value=['aws']), patch.object(b, 'recipient', return_value='public'), patch.object(b, 'verify_identity'), patch.object(b, 'capture', side_effect=b.BackupError('capture failed')), patch.object(b, 'upload_verified') as upload, patch.object(b, 'heartbeat') as heartbeat:
            with self.assertRaises(b.BackupError):
                b.backup('daily')
            upload.assert_not_called()
            heartbeat.assert_not_called()

    def test_failed_upload_cannot_publish_heartbeat(self):
        def capture(output, state):
            output.mkdir()
            (output / 'fixture').write_bytes(b'fixture')
            return {'created_at': 'timestamp', 'snapshot_status': {}}
        with patch.dict(b.os.environ, {'GITHUB_ACTIONS': 'true', 'TALOS_SECRETS_B64': 'aWQ='}), patch.object(b, 'aws_command', return_value=['aws']), patch.object(b, 'recipient', return_value='public'), patch.object(b, 'verify_identity'), patch.object(b, 'capture', side_effect=capture), patch.object(b, 'age_binary', return_value='age'), patch.object(b, 'run'), patch.object(b, 'upload_verified', side_effect=b.BackupError('readback failed')), patch.object(b, 'heartbeat') as heartbeat:
            with self.assertRaises(b.BackupError):
                b.backup('daily')
            heartbeat.assert_not_called()

    def test_child_process_does_not_receive_identity_environment(self):
        with patch.dict(b.os.environ, {'TALOS_SECRETS_B64': 'private'}), patch.object(b.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b'ok'
            b.run(['example'])
            self.assertNotIn('TALOS_SECRETS_B64', run.call_args.kwargs['env'])


if __name__ == '__main__':
    unittest.main()
