"""Pinned tool downloads recover bounded transport failures without trusting partial data."""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import talos_tools as tools


class DownloadTests(unittest.TestCase):
    def setUp(self):
        # Test upstream recovery independently of the CI runner's cache setting.
        environment = patch.dict(tools.os.environ, {'HOMELAB_DEPENDENCY_CACHE': '0'})
        environment.start()
        self.addCleanup(environment.stop)
        sleeper = patch.object(tools.time, 'sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.destination = Path(self.temp.name) / 'tool'
        self.payload = b'complete verified tool'
        self.digest = hashlib.sha256(self.payload).hexdigest()

    def test_talos_cache_keeps_checksum_failure_fatal(self):
        response = io.BytesIO(b'corrupt')
        response.headers = {}
        opener = MagicMock()
        opener.open.return_value = response
        with patch.dict(tools.os.environ, {'HOMELAB_DEPENDENCY_CACHE': '1'}), \
                patch('cache_download.urllib.request.build_opener', return_value=opener):
            with self.assertRaisesRegex(ValueError, 'checksum'):
                tools.download_verified('https://get.helm.sh/helm-test.tar.gz',
                                        self.destination, self.digest)
        self.assertEqual(opener.open.call_count, 1)
        self.assertFalse(self.destination.exists())

    def test_transport_timeout_retries_and_verifies(self):
        with patch.object(tools.urllib.request, 'urlopen', side_effect=[TimeoutError(), io.BytesIO(self.payload)]) as request:
            tools.download_verified('https://example.invalid/tool', self.destination, self.digest)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(self.destination.read_bytes(), self.payload)

    def test_exhaustion_is_bounded_and_preserves_existing_file(self):
        self.destination.write_bytes(b'previous tool')
        with patch.object(tools.urllib.request, 'urlopen', side_effect=TimeoutError()) as request:
            with self.assertRaises(TimeoutError):
                tools.download_verified('https://example.invalid/tool', self.destination, self.digest)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(self.destination.read_bytes(), b'previous tool')

    def test_integrity_failure_is_not_retried_or_written(self):
        with patch.object(tools.urllib.request, 'urlopen', return_value=io.BytesIO(b'corrupt')) as request:
            with self.assertRaisesRegex(ValueError, 'checksum'):
                tools.download_verified('https://example.invalid/tool', self.destination, self.digest)
        self.assertEqual(request.call_count, 1)
        self.assertFalse(self.destination.exists())

    def test_transient_http_failure_retries(self):
        error = HTTPError('https://example.invalid/tool', 503, 'Unavailable', {}, io.BytesIO())
        self.addCleanup(error.close)
        with patch.object(tools.urllib.request, 'urlopen', side_effect=[error, io.BytesIO(self.payload)]) as request:
            tools.download_verified('https://example.invalid/tool', self.destination, self.digest)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(self.destination.read_bytes(), self.payload)

    def test_permanent_http_error_is_not_retried(self):
        error = HTTPError('https://example.invalid/tool', 403, 'Forbidden', {}, io.BytesIO())
        self.addCleanup(error.close)
        with patch.object(tools.urllib.request, 'urlopen', side_effect=error) as request:
            with self.assertRaises(HTTPError):
                tools.download_verified('https://example.invalid/tool', self.destination, self.digest)
        self.assertEqual(request.call_count, 1)

    def test_partial_cli_download_is_discarded_before_retry(self):
        partial = MagicMock()
        partial.__enter__.return_value = partial
        partial.read.side_effect = [b'partial data', TimeoutError()]
        with patch.object(tools.Path, 'home', return_value=Path(self.temp.name)), \
                patch.object(tools.platform, 'system', return_value='Linux'), \
                patch.object(tools.platform, 'machine', return_value='x86_64'), \
                patch.dict(tools.HASHES, {('Linux', 'x86_64'): self.digest}), \
                patch.object(tools.urllib.request, 'urlopen', side_effect=[partial, io.BytesIO(self.payload)]):
            binary = tools.cli()
        self.assertEqual(binary.read_bytes(), self.payload)
        self.assertEqual(binary.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(binary.parent.iterdir()), [binary])


if __name__ == '__main__':
    unittest.main()
