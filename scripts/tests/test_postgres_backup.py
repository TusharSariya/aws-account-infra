import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'apps/platform/postgres'))
import backup
import restore


class FakeS3:
    def __init__(self, failure=None):
        self.failure = failure
        self.objects = {backup.KEY: [('original', b'old') ]}
        self.parts = []
        self.aborted = False
    def upload_file(self, path, bucket, key, **kwargs):
        if self.failure == 'upload':
            raise OSError('injected upload failure')
        self.objects[key] = [('staged', Path(path).read_bytes())]
    def head_object(self, Bucket, Key):
        return {'VersionId': self.objects[Key][-1][0]}
    def get_object(self, Bucket, Key, VersionId):
        data = next(data for version, data in self.objects[Key] if version == VersionId)
        if self.failure == 'checksum' and Key.startswith('staging/'):
            data += b'corrupt'
        return {'VersionId': VersionId, 'Body': io.BytesIO(data)}
    def create_multipart_upload(self, **kwargs):
        return {'UploadId': 'new'}
    def upload_part_copy(self, CopySource, **kwargs):
        if self.failure == 'copy':
            raise OSError('injected promotion failure')
        self.parts.append(self.objects[CopySource['Key']][-1][1])
        return {'CopyPartResult': {'ETag': 'part'}}
    def complete_multipart_upload(self, **kwargs):
        self.objects[backup.KEY].append(('published', b''.join(self.parts)))
        return {'VersionId': 'published'}
    def abort_multipart_upload(self, **kwargs):
        self.aborted = True


class BackupTests(unittest.TestCase):
    def test_stage_failures_never_replace_latest(self):
        for failure in ('upload', 'checksum', 'copy'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as name:
                path = Path(name) / 'archive'; path.write_bytes(b'complete backup')
                s3 = FakeS3(failure)
                with self.assertRaises((OSError, backup.BackupError)):
                    backup.publish(s3, 'bucket', 'kms', path, lambda: None)
                self.assertEqual(s3.objects[backup.KEY], [('original', b'old')])
                self.assertEqual(s3.aborted, failure == 'copy')

    def test_exact_version_publication_and_old_version_read(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'archive'; path.write_bytes(b'complete backup')
            s3 = FakeS3()
            result = backup.publish(s3, 'bucket', 'kms', path, lambda: None)
            self.assertEqual(result['version_id'], 'published')
            backup.verify_object(s3, 'bucket', backup.KEY, 'original', hashlib.sha256(b'old').hexdigest())
            self.assertEqual(len(s3.objects[backup.KEY]), 2)

    def test_lost_lock_cannot_publish(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'archive'; path.write_bytes(b'data')
            s3 = FakeS3()
            with self.assertRaises(ConnectionError):
                backup.publish(s3, 'bucket', 'kms', path, lambda: (_ for _ in ()).throw(ConnectionError()))
            self.assertEqual(s3.objects[backup.KEY], [('original', b'old')])

    def test_dump_failure_and_scratch_bound(self):
        with tempfile.TemporaryDirectory() as name:
            with self.assertRaises(backup.BackupError):
                backup.command_to_file([sys.executable, '-c', 'import sys;sys.exit(1)'], Path(name)/'dump', 100)
            with self.assertRaises(backup.BackupError):
                backup.command_to_file([sys.executable, '-c', 'print("x"*1000)'], Path(name)/'large', 100)

    def test_null_version_fails_closed(self):
        for response in ({}, {'VersionId': 'null'}):
            with self.assertRaises(backup.BackupError):
                backup.exact_version(response)

    def test_unsafe_archive_rejected(self):
        import tarfile
        with tempfile.TemporaryDirectory() as name:
            path = Path(name)
            with tarfile.open(path/'backup.tar.gz', 'w:gz') as a:
                item = tarfile.TarInfo('../escape'); item.size=1
                a.addfile(item, io.BytesIO(b'x'))
            with self.assertRaises(backup.BackupError):
                restore.unpack(path/'backup.tar.gz', path)


if __name__ == '__main__':
    unittest.main()
