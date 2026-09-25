import io
import unittest
from unittest.mock import patch
import urllib.error
import cache_transport
from cache_transport import Transport, rewrite_metadata


class Response(io.BytesIO):
    def __init__(self, body, length=None):
        super().__init__(body)
        self.headers = {'Content-Length': str(len(body) if length is None else length)}


class Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []
    def open(self, request, timeout):
        self.urls.append(request.full_url)
        assert not request.has_header('Authorization')
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class TransportTests(unittest.TestCase):
    def setUp(self):
        sleeper = patch.object(cache_transport.time, 'sleep')
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_bounded_cache_then_upstream(self):
        busy = [urllib.error.HTTPError('http://cache', 503, 'busy', {}, None) for _ in range(2)]
        opener = Opener(busy + [urllib.error.URLError('offline')] * 2 + [Response(b'complete')])
        body, _, source, attempts = Transport(opener=opener).read('/go/example.org/module/@v/v1.0.0.mod')
        with body:
            self.assertEqual(body.read(), b'complete')
        self.assertEqual((source, attempts), ('upstream', 3))
        # Backoff only between attempts on the same source; the switch is immediate.
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [1, 1, 2])
        self.assertEqual(len(opener.urls), 5)
        self.assertIn('/repository/go/', opener.urls[1])
        self.assertTrue(opener.urls[2].startswith('https://proxy.golang.org/'))

    def test_unreachable_cache_is_sidelined_after_one_connection_failure(self):
        opener = Opener([urllib.error.URLError('no route'), Response(b'first'), Response(b'second'),
                         Response(b'third-from-cache')])
        transport = Transport(opener=opener)
        with patch.object(cache_transport.time, 'monotonic', side_effect=[100.0, 100.0, 200.0, 500.0]):
            body, _, source, attempts = transport.read('/npm/example')
            with body:
                self.assertEqual(body.read(), b'first')
            self.assertEqual((source, attempts), ('upstream', 1))
            # One cache URL, then upstream; the second cache attempt and its backoff are skipped.
            self.assertEqual(len(opener.urls), 2)
            self.sleep.assert_not_called()
            body, _, source, _ = transport.read('/npm/example')
            with body:
                self.assertEqual(body.read(), b'second')
            self.assertEqual(source, 'upstream')
            self.assertEqual(len(opener.urls), 3)
            self.assertTrue(opener.urls[2].startswith('https://registry.npmjs.org/'))
            # After CACHE_DOWN_SECONDS the cache is tried again.
            body, _, source, _ = transport.read('/npm/example')
            with body:
                self.assertEqual(body.read(), b'third-from-cache')
            self.assertEqual(source, 'cache')
            self.assertIn('/repository/npm/', opener.urls[3])

    def test_interrupted_body_is_discarded(self):
        opener = Opener([Response(b'partial', 100), Response(b'complete')])
        body, _, source, attempts = Transport(opener=opener).read('/npm/example')
        with body:
            self.assertEqual(body.read(), b'complete')
        self.assertEqual((source, attempts), ('cache', 2))

    def test_complete_corrupt_body_is_left_for_package_integrity_verifier(self):
        opener = Opener([Response(b'corrupt')])
        body, _, _, _ = Transport(opener=opener).read('/npm/example/-/example.tgz')
        with body:
            self.assertEqual(body.read(), b'corrupt')
        self.assertEqual(len(opener.urls), 1)

    def test_unknown_routes_and_traversal_rejected_before_network(self):
        opener = Opener([])
        for route in ('https://evil.test/x', '/npm/../private', '/npm/%2e%2e/private', '/private/x', '/npm/x?token=secret'):
            with self.subTest(route=route), self.assertRaises(ValueError):
                Transport(opener=opener).read(route)
        self.assertEqual(opener.urls, [])

    def test_package_metadata_rewrites_urls_without_dropping_integrity(self):
        data = b'{"dist":{"tarball":"https://registry.npmjs.org/a/-/a.tgz","integrity":"sha512-proof"}}'
        rewritten = rewrite_metadata(io.BytesIO(data), 'application/json', '/npm/a', 'http://127.0.0.1:18082', 'http://nexus/repository/')
        self.assertIn(b'http://127.0.0.1:18082/npm/a/-/a.tgz', rewritten)
        self.assertIn(b'"integrity":"sha512-proof"', rewritten)
        html = b'<a href="https://files.pythonhosted.org/packages/x.whl#sha256=proof">x</a>'
        rewritten = rewrite_metadata(io.BytesIO(html), 'text/html', '/pypi/simple/x/', 'http://127.0.0.1:18082', '')
        self.assertIn(b'/raw-python-files/packages/x.whl#sha256=proof', rewritten)

    def test_apt_security_alias_keeps_exact_signed_path(self):
        opener = Opener([Response(b'signed metadata')])
        body, _, _, _ = Transport(opener=opener).read(
            'http://deb.debian.org/debian-security/dists/trixie-security/InRelease')
        body.close()
        self.assertTrue(opener.urls[0].endswith('/apt-debian-security/dists/trixie-security/InRelease'))

    def test_permanent_upstream_status_is_preserved_after_bounded_attempts(self):
        errors = [urllib.error.HTTPError('https://example.org', 404, 'missing', {}, None) for _ in range(5)]
        opener = Opener(errors)
        with self.assertRaises(urllib.error.HTTPError) as failure:
            Transport(opener=opener).read('/go/example.org/missing/@v/v1.0.0.mod')
        self.assertEqual(failure.exception.code, 404)
        self.assertEqual(len(opener.urls), 5)
        self.sleep.assert_not_called()

    def test_exact_python_fallback_artifact(self):
        metadata = b'{"urls":[{"filename":"x-1.whl","url":"https://files.pythonhosted.org/packages/ab/x-1.whl"}]}'
        opener = Opener([urllib.error.URLError('offline'), Response(metadata), Response(b'wheel')])
        body, _, source, _ = Transport(opener=opener).read('/pypi/packages/x/1/x-1.whl')
        with body:
            self.assertEqual(body.read(), b'wheel')
        self.assertEqual(source, 'upstream')
        self.assertEqual(opener.urls[-1], 'https://files.pythonhosted.org/packages/ab/x-1.whl')


if __name__ == '__main__':
    unittest.main()
