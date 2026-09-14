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
