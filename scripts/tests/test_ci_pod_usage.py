import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ci_pod_usage import AllocatedBlocks, image_files, overlay_paths, pod_cgroup


class AccountingTests(unittest.TestCase):
    def test_cgroup_namespace_relative_paths_do_not_escape_host_root(self):
        uid = 'a1ef38a6-ae0b-4e6d-9f54-e0bcc5c1fd55'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / 'kubepods' / ('pod' + uid)
            expected.mkdir(parents=True)
            self.assertEqual(pod_cgroup(root, uid), expected)
            with self.assertRaises(ValueError):
                pod_cgroup(root, '../../../' + uid)

    def test_shared_hardlinks_sparse_files_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / 'layer'
            payload.write_bytes(b'x' * 8192)
            os.link(payload, root / 'same-layer')
            sparse = root / 'sparse'
            with sparse.open('wb') as output:
                output.seek(64 * 1024 * 1024)
                output.write(b'x')
            link = root / 'external'
            link.symlink_to('/var')
            counter = AllocatedBlocks()
            counter.add_tree(root)
            expected = sum(path.lstat().st_blocks * 512 for path in [root, payload, sparse, link])
            self.assertEqual(counter.bytes, expected)
            self.assertLess(counter.bytes, sparse.stat().st_size)
            counter.add_tree(payload)
            self.assertEqual(counter.bytes, expected)

    def test_deleted_open_file_still_consumes_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'open'
            with path.open('wb') as output:
                output.write(b'x' * 8192)
                output.flush()
                before = os.fstat(output.fileno())
                path.unlink()
                counter = AllocatedBlocks()
                counter.add_stat(os.fstat(output.fileno()))
                self.assertEqual(counter.bytes, before.st_blocks * 512)
                self.assertGreater(counter.bytes, 0)

    def test_only_root_overlay_is_resolved(self):
        base = '/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/'
        line = f'10 2 0:1 / / rw - overlay overlay rw,lowerdir={base}1/fs:{base}2/fs,upperdir={base}3/fs,workdir={base}3/work'
        self.assertEqual(overlay_paths(line), [base + x for x in ['1/fs', '2/fs', '3/fs', '3/work']])
        with self.assertRaises(ValueError):
            overlay_paths(line.replace(base + '1/fs', '/retained/ai'))
        nested = '10 2 0:1 / / rw - overlay overlay rw,lowerdir=/scratch/docker/overlay2/layer,upperdir=/scratch/docker/overlay2/writable,workdir=/scratch/docker/overlay2/work'
        self.assertEqual(overlay_paths(nested), [])

    def test_image_config_is_counted_without_reading_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            content = Path(directory)
            digest = lambda letter: 'sha256:' + letter * 64
            (content / ('a' * 64)).write_text(json.dumps({'manifests': [
                {'platform': {'os': 'linux', 'architecture': 'amd64'}, 'digest': digest('b')},
                {'platform': {'os': 'linux', 'architecture': 'arm64'}, 'digest': digest('f')}]}))
            (content / ('b' * 64)).write_text(json.dumps({
                'config': {'digest': digest('c')}, 'layers': [{'digest': digest('d')}]}))
            (content / ('c' * 64)).write_bytes(b'not parsed as JSON; may contain image environment')
            (content / ('d' * 64)).write_bytes(b'compressed layer is stat only')
            paths, missing = image_files([digest('a')], content, 'amd64')
            self.assertEqual({path.name for path in paths}, {x * 64 for x in 'abcd'})
            self.assertFalse(missing)


if __name__ == '__main__':
    unittest.main()
