import hashlib
import http.client
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import urllib.error
from cache_download import CACHE, IntegrityError, cache_url, fetch


class Response(io.BytesIO):
    def __init__(self, body, length=None):
        super().__init__(body)
        self.headers = {'Content-Length': str(len(body) if length is None else length)}


class Opener:
    def __init__(self, results):
        self.results, self.urls = iter(results), []
    def open(self, url, timeout):
        self.urls.append(url)
        result = next(self.results)
        if isinstance(result, Exception): raise result
        return result


class DownloadTests(unittest.TestCase):
    url = 'https://github.com/example/releases/download/v1/tool.tar.gz'
    data = b'checksum-pinned fixture'

    def fetch(self, opener, use_cache=True):
        with TemporaryDirectory() as directory:
            target = Path(directory)/'tool'
            target.write_bytes(b'previous output')
            try:
                result = fetch(self.url, hashlib.sha256(self.data).hexdigest(), target,
                               use_cache=use_cache, opener=opener)
                self.assertEqual(target.read_bytes(), self.data)
                return result
            except Exception:
                self.assertEqual(target.read_bytes(), b'previous output')
                self.assertEqual([x.name for x in Path(directory).iterdir()], ['tool'])
                raise

    def test_two_cache_then_at_most_three_upstream_attempts(self):
        opener = Opener([urllib.error.URLError('unavailable')]*4+[Response(self.data)])
        self.assertEqual(self.fetch(opener)['attempts'], 5)
        self.assertEqual(opener.urls, [cache_url(self.url)]*2+[self.url]*3)
        opener = Opener([urllib.error.URLError('unavailable')]*5)
        with self.assertRaises(RuntimeError): self.fetch(opener)
        self.assertEqual(len(opener.urls), 5)

    def test_integrity_failure_is_fatal_without_fallback(self):
        opener = Opener([Response(b'corrupt'),Response(self.data)])
        with self.assertRaises(IntegrityError): self.fetch(opener)
        self.assertEqual(len(opener.urls), 1)

    def test_truncated_response_is_discarded_before_retry(self):
        opener = Opener([Response(b'partial', length=100), Response(self.data)])
        self.assertEqual(self.fetch(opener)['attempts'], 2)

    def test_upstream_recovery_does_not_contact_cache(self):
        opener = Opener([Response(self.data)])
        self.assertEqual(self.fetch(opener, use_cache=False)['source'], 'upstream')
        self.assertEqual(opener.urls, [self.url])

    def test_reviewed_origins_only(self):
        self.assertEqual(cache_url('https://go.dev/dl/go1.26.1.tar.gz'),CACHE+'raw-go/go1.26.1.tar.gz')
        for url in ['http://github.com/x','https://user:secret@github.com/x','https://unknown.invalid/x','https://go.dev/other']:
            with self.subTest(url=url), self.assertRaises(ValueError):cache_url(url)
