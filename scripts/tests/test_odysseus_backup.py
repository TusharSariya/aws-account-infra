"""Full-volume isolated restore and hostile archive rejection."""
import importlib.util
import io
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('archive', ROOT / 'apps/platform/recovery/archive.py')
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


class BackupTests(unittest.TestCase):
    def test_all_volumes_and_sqlite_are_restored_and_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            for volume in archive.VOLUMES:
                (source / volume).mkdir(parents=True)
                (source / volume / 'content').write_bytes(volume.encode())
            with sqlite3.connect(source / 'workspace/state.db') as db:
                db.execute('CREATE TABLE proof(value TEXT)')
                db.execute("INSERT INTO proof VALUES ('retained')")
            stream = io.BytesIO()
            archive.capture(source, stream)
            stream.seek(0)
            result = archive.restore(root / 'restored', stream)
            self.assertEqual(result['files'], 4)
            self.assertEqual(result['sqlite_databases'], 1)
            self.assertEqual(archive.inventory(source), archive.inventory(root / 'restored'))

    def test_internal_cache_links_roundtrip_without_dereferencing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            for volume in archive.VOLUMES:
                (source / volume).mkdir(parents=True)
            (source / 'workspace/blobs').mkdir()
            (source / 'workspace/blobs/model').write_bytes(b'model data')
            (source / 'workspace/snapshots/revision').mkdir(parents=True)
            (source / 'workspace/snapshots/revision/model').symlink_to('../../blobs/model')
            stream = io.BytesIO()
            archive.capture(source, stream)
            stream.seek(0)
            archive.restore(root / 'restored', stream)
            restored = root / 'restored/workspace/snapshots/revision/model'
            self.assertTrue(restored.is_symlink())
            self.assertEqual(restored.read_bytes(), b'model data')
            self.assertEqual(archive.inventory(source), archive.inventory(root / 'restored'))

    def test_cross_volume_missing_and_chained_links_are_rejected(self):
        for target in ('../models/data', 'missing', 'link', '/etc/passwd'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for volume in archive.VOLUMES:
                    (root / volume).mkdir()
                (root / 'models/data').write_text('data')
                (root / 'workspace/link').symlink_to(target)
                with self.assertRaises(ValueError):
                    archive.inventory(root)

    def test_link_target_cannot_hide_symlink_traversal_before_dotdot(self):
        for target in ('a/../file', 'missing/../file', 'file/../file'):
            entries = {'workspace/file': {'kind': 'file'},
                       'workspace/a': {'kind': 'symlink', 'target': 'file'},
                       'workspace/link': {'kind': 'symlink', 'target': target}}
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'non-directory'):
                archive.validate_links(entries)

    def test_link_entry_cannot_be_nested_under_another_link(self):
        entries = {'workspace/base': {'kind': 'directory'},
                   'workspace/deep': {'kind': 'directory'},
                   'workspace/file': {'kind': 'file'},
                   'workspace/deep/a': {'kind': 'symlink', 'target': '../base'},
                   'workspace/deep/a/b': {'kind': 'symlink', 'target': '../../file'}}
        with self.assertRaisesRegex(ValueError, 'entry traverses a non-directory'):
            archive.validate_links(entries)

    def test_archive_cannot_write_through_link_parent(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            stream = io.BytesIO()
            manifest = {'workspace/blob': {'kind': 'directory', 'mode': 493},
                        'workspace/link': {'kind': 'symlink', 'target': 'blob'},
                        'workspace/link/file': {'kind': 'file', 'mode': 420}}
            with tarfile.open(fileobj=stream, mode='w:gz') as output:
                data = json.dumps(manifest).encode()
                entry = tarfile.TarInfo('manifest.json'); entry.size = len(data)
                output.addfile(entry, io.BytesIO(data))
                entry = tarfile.TarInfo('workspace/blob'); entry.type = tarfile.DIRTYPE
                output.addfile(entry)
                entry = tarfile.TarInfo('workspace/link'); entry.type = tarfile.SYMTYPE; entry.linkname = 'blob'
                output.addfile(entry)
                entry = tarfile.TarInfo('workspace/link/file')
                output.addfile(entry, io.BytesIO())
            stream.seek(0)
            with self.assertRaises((ValueError, FileExistsError)):
                archive.restore(Path(directory) / 'restored', stream)
            self.assertFalse((Path(directory) / 'restored/workspace/blob/file').exists())

    def test_links_path_escape_and_duplicate_entries_are_rejected(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('workspace/link', tarfile.SYMTYPE), ('/escape', tarfile.REGTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode='w:gz') as output:
                    entry = tarfile.TarInfo(name)
                    entry.type = kind
                    entry.linkname = '/etc/passwd'
                    output.addfile(entry)
                stream.seek(0)
                with self.assertRaises(ValueError):
                    archive.restore(Path(directory) / 'restore', stream)

    def test_existing_target_and_source_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for volume in archive.VOLUMES:
                (root / volume).mkdir()
            (root / 'models/link').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):
                archive.inventory(root)
            with self.assertRaises(ValueError):
                archive.restore(root, io.BytesIO())
