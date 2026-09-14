import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'apps/platform/storage'))
import collector


class CollectorTests(unittest.TestCase):
    def test_unenrolled_uuid_cannot_touch_storage(self):
        with patch.object(collector, 'open_mount') as mount, self.assertRaises(ValueError):
            collector.guest({'filesystemUUID': ''})
        mount.assert_not_called()

    def test_wrong_filesystem_cannot_create_or_relabel_project(self):
        config = {'filesystemUUID': '1a6eb2f2-3217-4821-b595-e572153623fa'}
        with patch.object(collector, 'open_mount', return_value=10), \
             patch.object(collector, 'filesystem_uuid', return_value='other'), \
             patch.object(collector.os, 'close') as close, \
             patch.object(collector, 'open_project') as create, self.assertRaisesRegex(ValueError, 'UUID mismatch'):
            collector.guest(config)
        create.assert_not_called()
        close.assert_called_once_with(10)

    @patch('collector.ssl.create_default_context')
    @patch('collector.urllib.request.build_opener')
    def test_physical_collector_preserves_source_timestamp(self, build, context):
        snapshot = {name: {'identity': 'pve/data', 'healthy': True, 'measured_at': 100,
                           'used_percent': 10} for name in ('pool.data', 'pool.metadata')}
        response = build.return_value.open.return_value.__enter__.return_value
        response.read.return_value = json.dumps(snapshot).encode()
        result = collector.physical({'physicalURL': 'https://100.101.182.9:9443/capacity',
                                     'physicalPool': 'pve/data'})
        self.assertEqual(result, snapshot)
        context.assert_called_once_with(cafile='/physical-credentials/ca.crt')
        context.return_value.load_cert_chain.assert_called_once_with('/physical-credentials/tls.crt', '/physical-credentials/tls.key')

    @patch('collector.ssl.create_default_context')
    @patch('collector.urllib.request.build_opener')
    def test_missing_metadata_cannot_be_published_as_complete(self, build, context):
        build.return_value.open.return_value.__enter__.return_value.read.return_value = b'{"pool.data": {}}'
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            collector.physical({'physicalURL': 'https://100.101.182.9:9443/capacity', 'physicalPool': 'pve/data'})


if __name__ == '__main__':
    unittest.main()
