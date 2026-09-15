from pathlib import Path
import sys
import unittest

import httpx
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/containers/odysseus'))
from lifecycle.http_clients import install_http_hooks, inject
from lifecycle.tracking import Tracker, CURRENT


class HTTPTests(unittest.TestCase):
    def setUp(self):
        sync, asynchronous, send = install_http_hooks('workspace-fixture-token')
        self.addCleanup(setattr, httpx.Client, 'send', sync)
        self.addCleanup(setattr, httpx.AsyncClient, 'send', asynchronous)
        self.addCleanup(setattr, requests.Session, 'send', send)

    def test_redirect_is_not_followed_and_original_request_has_no_credentials(self):
        seen = []
        def transport(request):
            seen.append((str(request.url), dict(request.headers)))
            if request.url.host == 'external.example':
                return httpx.Response(200)
            return httpx.Response(302, headers={'location': 'http://external.example/'})
        with httpx.Client(transport=httpx.MockTransport(transport), follow_redirects=True) as client:
            request = client.build_request('GET', 'http://localhost:11434/api/tags')
            response = client.send(request)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0][1]['authorization'], 'Bearer workspace-fixture-token')
            self.assertNotIn('authorization', request.headers)
            client.get('http://external.example/')
            self.assertNotIn('authorization', seen[-1][1])

    def test_continuation_is_scoped_to_exact_local_destinations(self):
        tracker = Tracker('unused', '', '', transport=lambda *args: {})
        work = tracker.begin()
        token = CURRENT.set(work)
        try:
            for url in ('https://localhost:11434/api/chat', 'http://localhost.evil:11434/api/chat',
                        'http://localhost:11435/api/chat', 'http://external.example/'):
                headers = {}
                self.assertIsNone(inject(url, headers, 'model-token'))
                self.assertEqual(headers, {})
            headers = {}
            inject('http://localhost:11434/api/chat', headers, 'model-token')
            self.assertEqual(headers['X-Homelab-Work'], work.ticket)
        finally:
            CURRENT.reset(token)
            work.release()
