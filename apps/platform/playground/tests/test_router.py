"""Router tests: fit rule, GGUF derivation, refusal without waking, waking progress, pull registration,
per-backend path prefixes and the manual-power desktop backend."""
import http.client
import json
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fit  # noqa: E402
from catalog import Catalog  # noqa: E402
from router import Handler, Server, build  # noqa: E402

GEMMA3 = {'general.architecture': 'gemma3', 'gemma3.block_count': 62, 'gemma3.context_length': 131072,
          'gemma3.attention.head_count': 32, 'gemma3.attention.head_count_kv': 16, 'gemma3.attention.key_length': 128,
          'gemma3.attention.sliding_window': 1024}
UNKNOWN = {'general.architecture': 'newarch', 'newarch.block_count': 10, 'newarch.context_length': 4096,
           'newarch.attention.head_count': 8, 'newarch.attention.head_count_kv': 2, 'newarch.attention.key_length': 64}
TOKEN = 'u' * 40


class FakeOllama(BaseHTTPRequestHandler):
    """Ollama behind a wake gateway: cold answers 503 until `state['awake']` is set."""
    state = {'awake': True, 'models': {}, 'requests': [], 'running': [], 'chat_delay': 0.0, 'final': {}}

    def log_message(self, *_a):
        pass

    def reply(self, code, obj, retry_after=False):
        data = json.dumps(obj).encode()
        self.send_response(code)
        if retry_after:
            self.send_header('Retry-After', '10')
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.state['requests'].append(('GET', self.path))
        if not self.state['awake']:
            return self.reply(503, {'error': 'waking'})
        if self.path == '/api/version':
            return self.reply(200, {'version': 'fake'})
        if self.path == '/api/tags':
            return self.reply(200, {'models': [{'name': n, 'model': n, 'size': m['size'], 'digest': m['digest']}
                                              for n, m in self.state['models'].items()]})
        if self.path == '/api/ps':
            return self.reply(200, {'models': [{'name': n, 'model': n} for n in self.state['running']]})
        return self.reply(404, {})

    def do_DELETE(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0)) or 0) or b'{}')
        self.state['requests'].append(('DELETE', self.path, body))
        self.state['models'].pop(body.get('model'), None)
        return self.reply(200, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0)) or 0) or b'{}')
        self.state['requests'].append(('POST', self.path, body))
        if self.path == '/api/chat' and self.state.pop('chat_cold_once', False):
            self.state['awake'] = False  # the runtime went away between the probe and the request
            return self.reply(503, {'error': 'waking'}, retry_after=True)
        if not self.state['awake']:
            return self.reply(503, {'error': 'waking'}, retry_after=True)
        if self.path == '/api/show':
            return self.reply(200, {'model_info': self.state['models'][body['model']]['info']})
        if self.path == '/api/pull':
            self.state['models'][body['model']] = {'size': 16 * fit.GIB, 'digest': 'sha256:new', 'info': GEMMA3}
            lines = [{'status': 'pulling manifest'}, {'status': 'pulling abc', 'total': 10, 'completed': 10}, {'status': 'success'}]
        elif self.path in ('/api/chat', '/api/generate'):
            import time
            time.sleep(self.state['chat_delay'])
            lines = [{'model': body['model'], 'message': {'role': 'assistant', 'content': 'hi'}, 'done': False},
                     {'model': body['model'], 'done': True, 'eval_count': 1, **self.state['final']}]
        else:
            return self.reply(404, {})
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson')
        self.send_header('Transfer-Encoding', 'chunked')
        self.end_headers()
        for line in lines:
            data = (json.dumps(line) + '\n').encode()
            self.wfile.write(f'{len(data):x}\r\n'.encode() + data + b'\r\n')
        self.wfile.write(b'0\r\n\r\n')


class FakeDesktop(FakeOllama):
    """Ollama on the desktop, reached directly: no wake gateway, off means connection refused."""
    state = {}


def fresh_state():
    return {'awake': True, 'models': {}, 'requests': [], 'running': [], 'chat_delay': 0.0, 'final': {}}


class FakeKube:
    """Read-only cluster view: node, runtime pods and the kubelet stats summary."""

    def __init__(self):
        self.ready, self.working_set = True, 6 * fit.GIB

    def kubelet_stats(self, address):
        assert address == '10.0.0.222'
        return {'pods': [{'podRef': {'namespace': 'homelab-models', 'name': 'ai-runtime-1'},
                          'memory': {'workingSetBytes': self.working_set}}]}

    def get(self, path):
        if path.startswith('/api/v1/nodes/worker'):
            return {'status': {'conditions': [{'type': 'Ready', 'status': 'True'}],
                               'addresses': [{'type': 'InternalIP', 'address': '10.0.0.222'}]}}
        if '/pods?labelSelector=app%3Dai-runtime' in path or '/pods?labelSelector=app=ai-runtime' in path:
            return {'items': [{'metadata': {'name': 'ai-runtime-1'}, 'status': {'phase': 'Running',
                     'conditions': [{'type': 'Ready', 'status': 'True' if self.ready else 'False'}]}}]}
        return None


class FitTests(unittest.TestCase):
    def test_gemma3_matches_the_research_note(self):
        bpt, fixed, native, arch, exact = fit.derive(GEMMA3, 'f16')
        self.assertEqual((native, arch, exact), (131072, 'gemma3', True))
        self.assertEqual(bpt, 80 * 1024)            # 10 global layers, f16
        self.assertAlmostEqual(fixed / 2 ** 20, 624, delta=1)  # 52 SWA layers x 1536 cells
        bpt8, fixed8, *_ = fit.derive(GEMMA3, 'q8_0')
        self.assertEqual(bpt8, int(42.5 * 1024))
        self.assertAlmostEqual(fixed8 / 2 ** 20, 331.5, delta=1)

    def test_unknown_architecture_is_conservative(self):
        bpt, fixed, native, arch, exact = fit.derive(UNKNOWN, 'q8_0')
        self.assertFalse(exact)
        self.assertEqual(fixed, 0)
        self.assertEqual(bpt, int(10 * 2 * 2 * 64 * 34 / 32))

    def test_presets_and_snapping(self):
        self.assertEqual(fit.presets(131072), (8192, 16384, 32768, 131072))
        self.assertEqual(fit.presets(4096), (4096,))
        self.assertEqual(fit.snap_context(None, 131072), 8192)
        self.assertEqual(fit.snap_context(9000, 131072), 16384)
        self.assertEqual(fit.snap_context(40000, 131072), 131072)
        self.assertIsNone(fit.snap_context(200000, 131072))

    def test_fit_and_refusal_name_the_largest_preset(self):
        model = {'weight_bytes': 15 * fit.GIB, 'bytes_per_token': 42 * 1024, 'fixed_cache': 332 * 2 ** 20, 'native_max': 131072}
        backend = {'budget_bytes': 56 * fit.GIB, 'overhead_bytes': 6 * fit.GIB}
        fits, needed, largest = fit.fit(model, backend, 131072)
        self.assertTrue(fits)
        small = {'budget_bytes': 22 * fit.GIB, 'overhead_bytes': 6 * fit.GIB}
        fits, needed, largest = fit.fit(model, small, 131072)
        self.assertFalse(fits)
        self.assertEqual(largest, 16384)
        line = fit.refusal('m', 'server', 131072, needed, small['budget_bytes'], largest)
        self.assertIn('largest preset that fits is 16384', line)


class RouterTests(unittest.TestCase):
    def extra_backends(self):
        return []

    def setUp(self):
        FakeOllama.state = fresh_state()
        self.backend = ThreadingHTTPServer(('127.0.0.1', 0), FakeOllama)
        threading.Thread(target=self.backend.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.catalog = Catalog(Path(self.tmp.name) / 'catalog.sqlite')
        config = {'backends': [{'name': 'server', 'url': 'http://127.0.0.1:%d' % self.backend.server_address[1],
                                'budget_bytes': 56 * fit.GIB, 'overhead_bytes': 6 * fit.GIB, 'kv_type': 'q8_0',
                                'node': 'worker', 'namespace': 'homelab-models', 'runtime_selector': 'app=ai-runtime'}]
                  + self.extra_backends(),
                  'default_backend': 'server', 'poll_seconds': 0.2, 'wake_cap_seconds': 5}
        self.kube = FakeKube()
        self.server = Server(('127.0.0.1', 0), Handler)
        self.server.router = build(config, self.catalog, TOKEN, self.kube)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close()
        self.backend.shutdown(); self.backend.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, token=TOKEN):
        client = http.client.HTTPConnection(*self.server.server_address, timeout=30)
        headers = {'Authorization': 'Bearer ' + token} if token else {}
        client.request(method, path, None if body is None else json.dumps(body), headers)
        response = client.getresponse()
        data = response.read()
        client.close()
        return response.status, data

    def ndjson(self, data):
        return [json.loads(line) for line in data.decode().splitlines() if line.strip()]

    def test_auth_required(self):
        self.assertEqual(self.call('GET', '/api/tags', token='')[0], 401)
        self.assertEqual(self.call('GET', '/healthz', token='')[0], 200)

    def test_pull_registers_model_and_copy_then_tags_merges(self):
        status, data = self.call('POST', '/api/pull', {'model': 'hf.co/x/y:Q4_K_M'})
        self.assertEqual(status, 200)
        self.assertEqual(self.ndjson(data)[-1]['status'], 'success')
        model = self.catalog.model('hf.co/x/y:Q4_K_M')
        self.assertEqual(model['native_max'], 131072)
        self.assertEqual(model['bytes_per_token'], int(42.5 * 1024))
        self.assertEqual(self.catalog.copies('hf.co/x/y:Q4_K_M')[0]['backend'], 'server')
        status, data = self.call('GET', '/api/tags')
        listed = json.loads(data)['models'][0]
        self.assertEqual(listed['backends'], ['server'])
        self.assertFalse(listed['offline'])

    def test_oversized_context_is_refused_without_touching_the_backend(self):
        self.catalog.record_model('big', 15 * fit.GIB, 131072, int(42.5 * 1024), 332 * 2 ** 20, 'gemma3', True)
        self.catalog.record_copy('big', 'server', 'sha256:x')
        self.server.router.backends['server'].budget_bytes = 22 * fit.GIB
        FakeOllama.state['requests'].clear()
        status, data = self.call('POST', '/api/chat', {'model': 'big', 'messages': [], 'options': {'num_ctx': 131072}})
        lines = self.ndjson(data)
        self.assertEqual(status, 200)
        self.assertTrue(lines[-1]['done'])
        self.assertIn('does not fit on server', lines[-1]['message']['content'])
        self.assertIn('largest preset that fits is 16384', lines[-1]['message']['content'])
        self.assertEqual(FakeOllama.state['requests'], [])  # nothing woke, nothing was called
        self.server.router.catalog.set_override('big', True)
        status, data = self.call('POST', '/api/chat', {'model': 'big', 'messages': [], 'options': {'num_ctx': 131072}})
        self.assertEqual(self.ndjson(data)[-1].get('eval_count'), 1)  # override forwards

    def test_cold_backend_streams_waking_lines_then_the_answer(self):
        self.catalog.record_model('m', 15 * fit.GIB, 131072, int(42.5 * 1024), 332 * 2 ** 20, 'gemma3', True)
        self.catalog.record_copy('m', 'server', 'sha256:x')
        FakeOllama.state['awake'] = False
        threading.Timer(0.6, lambda: FakeOllama.state.update(awake=True)).start()
        status, data = self.call('POST', '/api/chat', {'model': 'm', 'messages': [{'role': 'user', 'content': 'hi'}]})
        lines = self.ndjson(data)
        contents = [l['message']['content'] for l in lines if 'message' in l]
        self.assertTrue(any(c.startswith('[waking] runtime starting') for c in contents))
        self.assertIn('[waking] ready\n', contents)
        self.assertEqual(contents[-1], 'hi')
        self.assertTrue(lines[-1]['done'])
        forwarded = [r for r in FakeOllama.state['requests'] if r[0] == 'POST' and r[1] == '/api/chat'][0][2]
        self.assertEqual(forwarded['options']['num_ctx'], 8192)  # missing num_ctx means the 8k preset

    def test_wake_cap_ends_the_stream_honestly(self):
        self.catalog.record_model('m', 1, 4096, 1, 0, 'x', True)
        self.catalog.record_copy('m', 'server', 'sha256:x')
        self.server.router.wake_cap_seconds = 0.3
        FakeOllama.state['awake'] = False
        status, data = self.call('POST', '/api/generate', {'model': 'm', 'prompt': 'x'})
        last = self.ndjson(data)[-1]
        self.assertTrue(last['done'])
        self.assertIn('gave up', last['response'])

    def chat(self, model='m'):
        status, data = self.call('POST', '/api/chat', {'model': model, 'messages': [{'role': 'user', 'content': 'x' * 400}]})
        lines = self.ndjson(data)
        return [l['message']['content'] for l in lines if 'message' in l]

    def test_silent_wait_names_the_stage_from_cluster_signals_and_learns_timings(self):
        self.catalog.record_model('m', 16 * fit.GIB, 131072, int(42.5 * 1024), 332 * 2 ** 20, 'gemma3', True)
        self.catalog.record_copy('m', 'server', 'sha256:x')
        FakeOllama.state['chat_delay'] = 0.5
        self.kube.ready = False
        contents = self.chat()
        self.assertTrue(any(c.startswith('[waking] runtime starting, 0:00 elapsed of ~0:30 typical') for c in contents), contents)
        self.kube.ready = True
        FakeOllama.state['final'] = {'load_duration': 65_000_000_000, 'prompt_eval_count': 265,
                                     'prompt_eval_duration': 35_000_000_000, 'eval_count': 100, 'eval_duration': 60_000_000_000}
        contents = self.chat()
        loading = [c for c in contents if c.startswith('[waking] loading weights')]
        self.assertTrue(loading, contents)
        self.assertIn(', 6.0 of 16.0 GiB in memory, 0:00 elapsed, no load measured yet for this model', loading[0])
        self.assertEqual(contents[-1], 'hi')
        timing = self.catalog.timing('m', 'server')
        self.assertEqual((timing['load_seconds'], round(timing['prompt_tps'], 2), round(timing['eval_tps'], 2)), (65.0, 7.57, 1.67))
        contents = self.chat()
        self.assertTrue(any('of ~1:05 typical for this model' in c for c in contents), contents)
        FakeOllama.state['running'] = ['m']
        FakeOllama.state['final'] = {'load_duration': 12_000_000, 'prompt_eval_count': 2, 'prompt_eval_duration': 100_000_000}
        contents = self.chat()
        prompt = [c for c in contents if c.startswith('[waking] processing prompt')]
        self.assertTrue(prompt, contents)
        self.assertIn('tokens at 7.6 tok/s', prompt[0])
        self.assertEqual(self.catalog.timing('m', 'server')['load_seconds'], 65.0)  # a warm answer keeps the real load
        self.kube.working_set = None
        FakeOllama.state['running'] = []
        contents = self.chat()
        self.assertTrue(any(c.startswith('[waking] loading weights, 16.0 GiB, 0:00 elapsed of ~1:05') for c in contents), contents)

    def test_gateway_503_during_the_silent_wait_is_a_cold_restart_not_an_error(self):
        self.catalog.record_model('m', 1, 4096, 1, 0, 'x', True)
        self.catalog.record_copy('m', 'server', 'sha256:x')
        FakeOllama.state['awake'] = True
        FakeOllama.state['chat_cold_once'] = True
        threading.Timer(0.5, lambda: FakeOllama.state.update(awake=True)).start()
        contents = self.chat()
        self.assertEqual(contents[-1], 'hi')
        self.assertIn('[waking] ready\n', contents)
        chats = [r for r in FakeOllama.state['requests'] if r[0] == 'POST' and r[1] == '/api/chat']
        self.assertEqual(len(chats), 2)

    def test_wake_cap_during_the_cold_restart_retry_ends_the_stream_once(self):
        self.catalog.record_model('m', 1, 4096, 1, 0, 'x', True)
        self.catalog.record_copy('m', 'server', 'sha256:x')
        self.server.router.wake_cap_seconds = 0.3
        FakeOllama.state['chat_cold_once'] = True  # probe passes, the chat meets a 503, it never wakes again
        body = json.dumps({'model': 'm', 'messages': []})
        # Raw bytes: http.client silently skips a stray terminator, the next response parser may not.
        with socket.create_connection(self.server.server_address, timeout=30) as sock:
            sock.sendall((f'POST /api/chat HTTP/1.1\r\nHost: router\r\nAuthorization: Bearer {TOKEN}\r\n'
                          f'Content-Length: {len(body)}\r\nConnection: close\r\n\r\n{body}').encode())
            data = b''
            while chunk := sock.recv(65536):
                data += chunk
        self.assertIn(b'gave up', data)
        self.assertTrue(data.endswith(b'}\n\r\n0\r\n\r\n'), data[-40:])  # the last chunk, then one terminator

    def test_delete_removes_copies_and_catalog_row(self):
        self.call('POST', '/api/pull', {'model': 'hf.co/x/y:Q4_K_M'})
        status, data = self.call('DELETE', '/api/delete', {'model': 'hf.co/x/y:Q4_K_M'})
        self.assertEqual(json.loads(data)['backends'], {'server': 'deleted'})
        self.assertNotIn('hf.co/x/y:Q4_K_M', FakeOllama.state['models'])
        self.assertIsNone(self.catalog.model('hf.co/x/y:Q4_K_M'))


class DesktopRouterTests(RouterTests):
    """Every root test again with a manual-power desktop configured, plus the /b/<name> connections."""

    def extra_backends(self):
        FakeDesktop.state = fresh_state()
        self.desktop = ThreadingHTTPServer(('127.0.0.1', 0), FakeDesktop)
        threading.Thread(target=self.desktop.serve_forever, daemon=True).start()
        # The chart's desktop entry: no token_file, node, namespace or runtime_selector.
        return [{'name': 'desktop', 'url': 'http://127.0.0.1:%d' % self.desktop.server_address[1],
                 'budget_bytes': 30 * fit.GIB, 'overhead_bytes': 2 * fit.GIB, 'kv_type': 'q8_0', 'manual_power': True}]

    def tearDown(self):
        super().tearDown()
        self.power_off()

    def power_off(self):
        self.desktop.shutdown(); self.desktop.server_close()

    def server_requests(self):
        return [r for r in FakeOllama.state['requests'] if r[1] != '/api/version']

    def test_desktop_backend_needs_no_token_and_no_cluster_reads(self):
        desktop = self.server.router.backends['desktop']
        self.assertNotIn('Authorization', desktop.headers())
        self.assertIsNone(desktop.runtime_memory())
        self.assertIsNone(desktop.runtime_ready())

    def test_prefix_pull_lands_on_that_backend_and_tags_filter_per_prefix(self):
        status, data = self.call('POST', '/b/desktop/api/pull', {'model': 'd:q4', 'backend': 'server'})
        self.assertEqual(self.ndjson(data)[-1]['status'], 'success')
        self.assertIn('d:q4', FakeDesktop.state['models'])
        self.assertEqual(FakeOllama.state['models'], {})  # the body's backend field loses to the prefix
        self.call('POST', '/b/server/api/pull', {'model': 's:q4'})
        self.assertEqual([c['backend'] for c in self.catalog.copies('d:q4')], ['desktop'])
        desktop = [m['name'] for m in json.loads(self.call('GET', '/b/desktop/api/tags')[1])['models']]
        server = [m['name'] for m in json.loads(self.call('GET', '/b/server/api/tags')[1])['models']]
        root = sorted(m['name'] for m in json.loads(self.call('GET', '/api/tags')[1])['models'])
        self.assertEqual((desktop, server, root), (['d:q4'], ['s:q4'], ['d:q4', 's:q4']))

    def test_prefix_chat_goes_to_that_backend_even_when_the_default_has_a_copy(self):
        self.catalog.record_model('m', 1, 4096, 1, 0, 'x', True)
        self.catalog.record_copy('m', 'server', 'sha256:x')
        self.catalog.record_copy('m', 'desktop', 'sha256:x')
        status, data = self.call('POST', '/b/desktop/api/chat', {'model': 'm', 'messages': [], 'backend': 'server'})
        self.assertEqual(self.ndjson(data)[-1].get('eval_count'), 1)
        self.assertTrue(any(r[1] == '/api/chat' for r in FakeDesktop.state['requests']))
        self.assertFalse(any(r[1] == '/api/chat' for r in FakeOllama.state['requests']))
        self.call('POST', '/api/chat', {'model': 'm', 'messages': []})  # root still prefers the default
        self.assertTrue(any(r[1] == '/api/chat' for r in FakeOllama.state['requests']))
        status, data = self.call('POST', '/b/desktop/api/generate', {'model': 'm', 'prompt': 'x', 'stream': False})
        self.assertEqual(status, 200)

    def test_unknown_prefix_is_a_404(self):
        status, data = self.call('GET', '/b/laptop/api/tags')
        self.assertEqual(status, 404)
        self.assertIn('unknown backend laptop', json.loads(data)['error'])
        self.assertEqual(self.call('POST', '/b/laptop/api/chat', {'model': 'm'})[0], 404)
        self.assertEqual(self.call('GET', '/b/desktop/api/tags', token='')[0], 401)

    def test_desktop_off_is_refused_at_once_without_touching_the_server(self):
        self.catalog.record_model('m', 1, 4096, 1, 0, 'x', True)
        self.catalog.record_copy('m', 'server', 'sha256:x')
        self.catalog.record_copy('m', 'desktop', 'sha256:x')
        self.call('GET', '/b/desktop/api/version')  # remember the desktop's version while it is up
        self.power_off()
        FakeOllama.state['requests'].clear()
        status, data = self.call('POST', '/b/desktop/api/chat', {'model': 'm', 'messages': []})
        last = self.ndjson(data)[-1]
        self.assertTrue(last['done'])
        self.assertIn('desktop is off, power it on and retry', last['message']['content'])
        status, data = self.call('POST', '/b/desktop/api/generate', {'model': 'm', 'prompt': 'x', 'stream': False})
        self.assertEqual(status, 503)
        self.assertIn('desktop is off, power it on and retry', json.loads(data)['error'])
        status, data = self.call('POST', '/b/desktop/api/pull', {'model': 'n'})
        self.assertIn('desktop is off, power it on and retry', self.ndjson(data)[-1]['status'])
        self.assertEqual(self.call('POST', '/b/desktop/api/show', {'model': 'm'})[0], 503)
        self.assertEqual(FakeOllama.state['requests'], [])  # no fallback, no wake, not even a probe
        status, data = self.call('GET', '/b/desktop/api/version')
        self.assertEqual((status, json.loads(data)), (200, {'version': 'fake'}))
        self.assertEqual(json.loads(self.call('GET', '/b/desktop/api/ps')[1]), {'models': []})
        listed = json.loads(self.call('GET', '/b/desktop/api/tags')[1])['models']
        self.assertEqual([(m['name'], m['offline']) for m in listed], [('m', True)])
        self.assertEqual(FakeOllama.state['requests'], [])
        root = json.loads(self.call('GET', '/api/tags')[1])['models']
        self.assertEqual(sorted(root[0]['backends']), ['desktop', 'server'])  # the off copy stays listed

    def test_desktop_going_off_mid_request_is_refused_not_retried(self):
        self.catalog.record_model('m', 1, 4096, 1, 0, 'x', True)
        self.catalog.record_copy('m', 'desktop', 'sha256:x')
        FakeDesktop.state['chat_cold_once'] = True  # the probe passes, then the host is gone
        status, data = self.call('POST', '/b/desktop/api/chat', {'model': 'm', 'messages': []})
        lines = self.ndjson(data)
        self.assertTrue(lines[-1]['done'])
        self.assertIn('desktop is off, power it on and retry', lines[-1]['message']['content'])
        self.assertFalse(any(l['message']['content'].startswith('[waking]') for l in lines))
        self.assertEqual(len([r for r in FakeDesktop.state['requests'] if r[1] == '/api/chat']), 1)

    def test_desktop_off_version_without_a_known_version_names_the_refusal(self):
        self.power_off()
        FakeOllama.state['requests'].clear()
        # The server answered no probe yet in this process; nothing is known, so say why.
        self.server.router.backends['server'].version = None
        status, data = self.call('GET', '/b/desktop/api/version')
        self.assertEqual(status, 503)
        self.assertIn('desktop is off, power it on and retry', json.loads(data)['error'])
        self.assertEqual(FakeOllama.state['requests'], [])

    def test_delete_on_an_off_backend_is_applied_on_the_next_awake_merge(self):
        self.call('POST', '/b/desktop/api/pull', {'model': 'd:q4'})
        self.call('POST', '/b/server/api/pull', {'model': 'd:q4'})
        FakeDesktop.state['awake'] = False  # asleep: 503 on every call
        status, data = self.call('DELETE', '/api/delete', {'model': 'd:q4'})
        self.assertEqual(json.loads(data)['backends'], {'server': 'deleted', 'desktop': 'pending: backend asleep'})
        self.assertIn('d:q4', FakeDesktop.state['models'])
        self.assertEqual(json.loads(self.call('GET', '/api/tags')[1])['models'], [])
        FakeDesktop.state['awake'] = True
        self.assertEqual(json.loads(self.call('GET', '/api/tags')[1])['models'], [])  # did not reappear
        self.assertNotIn('d:q4', FakeDesktop.state['models'])
        self.assertEqual(self.catalog.pending_deletes('desktop'), [])

    def test_prefix_delete_removes_only_that_copy(self):
        self.call('POST', '/b/desktop/api/pull', {'model': 'd:q4'})
        self.call('POST', '/b/server/api/pull', {'model': 'd:q4'})
        status, data = self.call('DELETE', '/b/desktop/api/delete', {'model': 'd:q4'})
        self.assertEqual(json.loads(data)['backends'], {'desktop': 'deleted'})
        self.assertEqual([c['backend'] for c in self.catalog.copies('d:q4')], ['server'])
        self.assertIsNotNone(self.catalog.model('d:q4'))
        self.assertIn('d:q4', FakeOllama.state['models'])


if __name__ == '__main__':
    unittest.main()
