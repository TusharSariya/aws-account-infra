"""Exercise the real directory boundary with the production cache catalog."""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/platform/storage'))
import xfs


class CacheProjectPaths(unittest.TestCase):
    def test_each_reviewed_cache_directory_can_be_created(self):
        volumes = json.loads((ROOT / 'config/environments/kubernetes/homelab-ci/cache-storage.json').read_text())
        with TemporaryDirectory() as directory:
            mount = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                for volume in volumes.values():
                    fd = xfs.open_project(mount, volume['path'])
                    os.close(fd)
                    self.assertTrue((Path(directory) / volume['path']).is_dir())
                for invalid in ('ci-cache-other', '../ci-cache-blobs', 'ci-cache-blobs/child', '/ci-cache-blobs'):
                    with self.assertRaises(ValueError):
                        xfs.open_project(mount, invalid)
            finally:
                os.close(mount)

    def test_cache_project_cannot_follow_a_symlink(self):
        with TemporaryDirectory() as directory, TemporaryDirectory() as outside:
            (Path(directory) / 'ci-cache-blobs').symlink_to(outside, target_is_directory=True)
            mount = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with self.assertRaises(OSError):
                    xfs.open_project(mount, 'ci-cache-blobs')
            finally:
                os.close(mount)
