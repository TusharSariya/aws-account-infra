"""Model playground router: the Ollama API in front of inference backends (docs/model-playground.md).

Intercepts /api/tags (merge), /api/pull (backend choice, wake, progress), /api/chat and
/api/generate (fit rule, wake, progress). Everything else passes through to the backend
that holds the model. Bearer auth on both hops. See ADR 0001.
"""
import hmac
import json
import os
import queue
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fit  # noqa: E402
from catalog import Catalog  # noqa: E402

INTERCEPTED = {'/api/tags', '/api/pull', '/api/chat', '/api/generate', '/api/delete'}
PASSTHROUGH_PREFIXES = ('/api/', '/v1/')
WAKING_PREFIX = '[waking] '
TYPICAL = {'host powering on': 60, 'worker joining': 300, 'runtime queued': None, 'runtime starting': 30,
           'model loading': 40, 'ready': None}


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


class Backend:
    """One inference backend: Ollama reached through its wake gateway, plus how to name its wake stages."""

    def __init__(self, spec, kube=None):
        self.name = spec['name']
        self.url = spec['url'].rstrip('/')
        self.budget_bytes = int(spec['budget_bytes'])
        self.overhead_bytes = int(spec['overhead_bytes'])
        self.kv_type = spec.get('kv_type', 'q8_0')
        self.manual_power = bool(spec.get('manual_power', False))
        self.node = spec.get('node')
        self.runtime_selector = spec.get('runtime_selector')
        self.namespace = spec.get('namespace', 'homelab-models')
        token_file = spec.get('token_file')
        self.token = Path(token_file).read_text().strip() if token_file else ''
        self.kube = kube

    def headers(self, extra=None):
        h = {'Content-Type': 'application/json'}
        if self.token:
            h['Authorization'] = 'Bearer ' + self.token
        h.update(extra or {})
        return h

    def request(self, method, path, body=None, timeout=20):
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        req = urllib.request.Request(self.url + path, data=data, headers=self.headers(), method=method)
        return urllib.request.urlopen(req, timeout=timeout)

    def json(self, method, path, body=None, timeout=20):
        with self.request(method, path, body, timeout) as r:
            return json.load(r)

    def awake(self):
        """True when the gateway proxies Ollama (200), False on 503 or connection failure."""
        try:
            with self.request('GET', '/api/version', timeout=10) as r:
                return r.status == 200
        except urllib.error.HTTPError as e:
            return e.code not in (502, 503, 504)
        except (urllib.error.URLError, socket.timeout, OSError):
            return False

    def stage(self, elapsed):
        """Name the wake stage from what the cluster shows; honest fallbacks when it cannot tell."""
        if self.kube is None or not self.node:
            return 'runtime starting'
        node = self.kube.get(f'/api/v1/nodes/{self.node}')
        if node is None:
            return 'host powering on' if elapsed < 90 else 'worker joining'
        ready = any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in node.get('status', {}).get('conditions', []))
        if not ready:
            return 'host powering on' if elapsed < 90 else 'worker joining'
        pods = self.kube.get(f'/api/v1/namespaces/{self.namespace}/pods?labelSelector={self.runtime_selector}') or {}
        items = pods.get('items', [])
        if not items:
            return 'runtime starting'
        pod = items[0]
        phase = pod.get('status', {}).get('phase')
        if phase == 'Pending' and not pod.get('status', {}).get('containerStatuses'):
            return 'runtime queued'
        return 'runtime starting'


class Kubernetes:
    """Read-only in-cluster adapter for naming wake stages. None on any failure, never raises."""

    def __init__(self):
        import ssl
        creds = Path('/var/run/secrets/kubernetes.io/serviceaccount')
        self.token = (creds / 'token').read_text().strip()
        self.context = ssl.create_default_context(cafile=str(creds / 'ca.crt'))
        self.base = 'https://' + os.environ['KUBERNETES_SERVICE_HOST'] + ':' + os.environ.get('KUBERNETES_SERVICE_PORT', '443')

    def get(self, path):
        req = urllib.request.Request(self.base + path, headers={'Authorization': 'Bearer ' + self.token})
        try:
            with urllib.request.urlopen(req, context=self.context, timeout=5) as r:
                return json.load(r)
        except Exception:  # noqa: BLE001 - observation only
            return None


class Router:
    def __init__(self, config, catalog, backends, ui_token):
        self.config = config
        self.catalog = catalog
        self.backends = {b.name: b for b in backends}
        self.default_backend = config.get('default_backend', backends[0].name)
        self.ui_token = ui_token
        self.poll_seconds = float(config.get('poll_seconds', 10))
        self.wake_cap_seconds = float(config.get('wake_cap_seconds', 1500))

    # ----- catalog reconciliation -----
    def register_from_backend(self, backend, name, digest=None):
        """Derive fit numbers from the backend's /api/show and record the model and its copy."""
        show = backend.json('POST', '/api/show', {'model': name})
        info = show.get('model_info', {})
        bytes_per_token, fixed_cache, native_max, arch, exact = fit.derive(info, backend.kv_type)
        weight = 0
        for entry in backend.json('GET', '/api/tags').get('models', []):
            if entry.get('name') == name or entry.get('model') == name:
                weight = int(entry.get('size', 0))
                digest = digest or entry.get('digest', '')
        if not weight:
            raise ValueError('backend does not list the pulled model')
        self.catalog.record_model(name, weight, native_max, bytes_per_token, fixed_cache, arch, exact)
        self.catalog.record_copy(name, backend.name, digest or '')

    def merged_tags(self):
        models = {}
        for backend in self.backends.values():
            if not backend.awake():
                continue
            try:
                listed = backend.json('GET', '/api/tags').get('models', [])
            except Exception:  # noqa: BLE001
                continue
            for entry in listed:
                name = entry.get('name') or entry.get('model')
                if self.catalog.model(name) is None:
                    try:
                        self.register_from_backend(backend, name, entry.get('digest'))
                    except Exception:  # noqa: BLE001 - unknown header shapes stay unlisted, not fatal
                        continue
                else:
                    self.catalog.record_copy(name, backend.name, entry.get('digest', ''))
                models.setdefault(name, {**entry, 'backends': [], 'offline': False})['backends'].append(backend.name)
        for copy in self.catalog.copies():
            name = copy['model']
            if name in models:
                if copy['backend'] not in models[name]['backends']:
                    models[name]['backends'].append(copy['backend'])
                continue
            model = self.catalog.model(name) or {}
            models[name] = {'name': name, 'model': name, 'size': model.get('weight_bytes', 0), 'digest': copy['digest'],
                            'modified_at': now_iso(), 'details': {'family': model.get('architecture')},
                            'backends': [copy['backend']], 'offline': True}
        return {'models': list(models.values())}

    # ----- routing decisions -----
    def backend_for(self, model_name, requested=None):
        if requested:
            return self.backends.get(requested)
        copies = [c['backend'] for c in self.catalog.copies(model_name)]
        if self.default_backend in copies:
            return self.backends[self.default_backend]
        for name in copies:
            if name in self.backends:
                return self.backends[name]
        return None

    def check_fit(self, model_name, backend, options):
        """Return (context, refusal_line_or_None)."""
        model = self.catalog.model(model_name)
        if model is None:
            return None, f'{model_name} is not in the catalog; pull it first.'
        requested = (options or {}).get('num_ctx')
        context = fit.snap_context(requested, model['native_max'])
        requested = requested if requested is not None else min(fit.DEFAULT_CONTEXT, model['native_max'])
        if context is None:
            return None, (f'Context {requested} exceeds the native maximum {model["native_max"]} of {model_name}.'
                          f' Presets: {", ".join(str(p) for p in fit.presets(model["native_max"]))}.')
        if model['fit_override']:
            return context, None
        spec = {'budget_bytes': backend.budget_bytes, 'overhead_bytes': backend.overhead_bytes}
        fits, needed, largest = fit.fit(model, spec, context)
        if fits:
            return context, None
        return context, fit.refusal(model_name, backend.name, context, needed, backend.budget_bytes, largest)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args):
        pass

    @property
    def router(self):
        return self.server.router

    # ----- plumbing -----
    def send_json(self, code, value):
        data = json.dumps(value).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def start_ndjson(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Transfer-Encoding', 'chunked')
        self.end_headers()

    def chunk(self, obj):
        data = (json.dumps(obj) + '\n').encode()
        self.wfile.write(f'{len(data):x}\r\n'.encode() + data + b'\r\n')
        self.wfile.flush()

    def end_chunks(self):
        self.wfile.write(b'0\r\n\r\n')
        self.wfile.flush()

    def authorized(self):
        expected = 'Bearer ' + self.router.ui_token
        if hmac.compare_digest(self.headers.get('Authorization', ''), expected):
            return True
        self.send_json(401, {'error': 'Bearer authentication required'})
        return False

    def body_json(self):
        length = int(self.headers.get('Content-Length', '0') or 0)
        raw = self.rfile.read(length) if length else b''
        return (json.loads(raw) if raw else {}), raw

    def progress(self, kind, model, text):
        if kind == 'chat':
            self.chunk({'model': model, 'created_at': now_iso(), 'message': {'role': 'assistant', 'content': text}, 'done': False})
        elif kind == 'generate':
            self.chunk({'model': model, 'created_at': now_iso(), 'response': text, 'done': False})
        else:
            self.chunk({'status': text})

    def final(self, kind, model, text):
        if kind == 'chat':
            self.chunk({'model': model, 'created_at': now_iso(), 'message': {'role': 'assistant', 'content': text},
                        'done': True, 'done_reason': 'stop'})
        elif kind == 'generate':
            self.chunk({'model': model, 'created_at': now_iso(), 'response': text, 'done': True, 'done_reason': 'stop'})
        else:
            self.chunk({'status': text})
        self.end_chunks()

    def wait_awake(self, backend, kind, model):
        """Trigger the wake by probing the gateway; stream stage lines until it proxies. False on cap."""
        if backend.awake():
            return True
        if backend.manual_power:
            self.final(kind, model, f'{backend.name} is off, power it on and retry.')
            return False
        started = time.monotonic()
        last_stage = None
        while True:
            elapsed = int(time.monotonic() - started)
            if elapsed > self.router.wake_cap_seconds:
                self.final(kind, model, f'{WAKING_PREFIX}gave up after {elapsed // 60} min at stage "{last_stage}"; '
                                        'the wake continues in the background, try again in a few minutes.')
                return False
            stage = backend.stage(elapsed)
            typical = TYPICAL.get(stage)
            line = f'{WAKING_PREFIX}{stage}, {elapsed // 60}:{elapsed % 60:02d} elapsed'
            line += f' of ~{typical // 60}:{typical % 60:02d} typical\n' if typical else '\n'
            self.progress(kind, model, line)
            last_stage = stage
            time.sleep(self.router.poll_seconds)
            if backend.awake():
                self.progress(kind, model, f'{WAKING_PREFIX}ready\n')
                return True

    def stream_upstream(self, backend, path, raw, kind, model, loading_note=True):
        """Forward a streaming request; while the backend is silent (model load) keep emitting a line."""
        req = urllib.request.Request(backend.url + path, data=raw, headers=backend.headers(), method='POST')
        first = queue.Queue()
        holder = {}

        def open_upstream():
            try:
                holder['response'] = urllib.request.urlopen(req, timeout=3600)
                first.put('ok')
            except urllib.error.HTTPError as e:
                holder['error'] = (e.code, e.read()[:500])
                first.put('http')
            except Exception as e:  # noqa: BLE001
                holder['error'] = (502, repr(e).encode())
                first.put('err')

        threading.Thread(target=open_upstream, daemon=True).start()
        waited = 0
        while True:
            try:
                first.get(timeout=self.router.poll_seconds)
                break
            except queue.Empty:
                waited += int(self.router.poll_seconds)
                if loading_note:
                    self.progress(kind, model, f'{WAKING_PREFIX}model loading, {waited // 60}:{waited % 60:02d} elapsed of ~0:40 typical\n')
        if 'error' in holder:
            code, detail = holder['error']
            self.progress(kind, model, f'{backend.name} answered {code}: {detail.decode(errors="replace")}')
            return
        with holder['response'] as upstream:
            for line in upstream:
                self.wfile.write(f'{len(line):x}\r\n'.encode() + line + b'\r\n')
                self.wfile.flush()
                yield line

    # ----- routes -----
    def do_GET(self):
        if self.path == '/healthz':
            return self.send_json(200, {'ready': True})
        if not self.authorized():
            return
        if self.path == '/api/tags':
            return self.send_json(200, self.router.merged_tags())
        if self.path == '/admin/catalog':
            return self.send_json(200, {'models': self.router.catalog.models(), 'copies': self.router.catalog.copies()})
        return self.passthrough('GET')

    def do_DELETE(self):
        if not self.authorized():
            return
        if self.path == '/api/delete':
            return self.delete()
        return self.passthrough('DELETE')

    def do_POST(self):
        if not self.authorized():
            return
        if self.path == '/api/chat' or self.path == '/api/generate':
            return self.inference('chat' if self.path == '/api/chat' else 'generate')
        if self.path == '/api/pull':
            return self.pull()
        if self.path == '/api/delete':
            return self.delete()
        if self.path == '/admin/override':
            body, _ = self.body_json()
            ok = self.router.catalog.set_override(body.get('model', ''), body.get('enabled', False))
            return self.send_json(200 if ok else 404, {'model': body.get('model'), 'fit_override': bool(body.get('enabled'))} if ok else {'error': 'unknown model'})
        return self.passthrough('POST')

    def inference(self, kind):
        body, raw = self.body_json()
        model = body.get('model', '')
        backend = self.router.backend_for(model, body.get('backend'))
        stream = body.get('stream', True)
        if backend is None:
            if not stream:
                return self.send_json(404, {'error': f'{model} is not on any backend; pull it first.'})
            self.start_ndjson()
            return self.final(kind, model, f'{model} is not on any backend; pull it first.')
        context, refusal = self.router.check_fit(model, backend, body.get('options'))
        if refusal:
            if not stream:
                return self.send_json(200, {'model': model, 'done': True, **({'message': {'role': 'assistant', 'content': refusal}} if kind == 'chat' else {'response': refusal})})
            self.start_ndjson()
            return self.final(kind, model, refusal)
        body.setdefault('options', {})['num_ctx'] = context
        body.pop('backend', None)
        raw = json.dumps(body).encode()
        if not stream:
            if not backend.awake():
                return self.send_json(503, {'error': f'{backend.name} is waking; retry, or stream to watch progress'})
            return self.forward(backend, 'POST', self.path, raw)
        self.start_ndjson()
        if not self.wait_awake(backend, kind, model):
            return
        for _ in self.stream_upstream(backend, self.path, raw, kind, model):
            pass
        self.end_chunks()

    def pull(self):
        body, _ = self.body_json()
        model = body.get('model') or body.get('name', '')
        backend = self.router.backends.get(body.get('backend') or self.router.default_backend)
        if backend is None:
            return self.send_json(404, {'error': 'unknown backend'})
        self.start_ndjson()
        if not self.wait_awake(backend, 'pull', model):
            return
        started = self.router.catalog.pull_started(model, backend.name)
        status = 'failed'
        raw = json.dumps({'model': model, 'stream': True}).encode()
        for line in self.stream_upstream(backend, '/api/pull', raw, 'pull', model, loading_note=False):
            try:
                if json.loads(line).get('status') == 'success':
                    status = 'success'
            except ValueError:
                pass
        self.router.catalog.pull_finished(model, backend.name, started, status)
        if status == 'success':
            try:
                self.router.register_from_backend(backend, model)
            except Exception:  # noqa: BLE001 - listed on next tags merge instead
                pass
        self.end_chunks()  # After registration, so a client that acts on 'success' finds the catalog row.

    def delete(self):
        body, raw = self.body_json()
        model = body.get('model') or body.get('name', '')
        results = {}
        for copy in self.router.catalog.copies(model):
            backend = self.router.backends.get(copy['backend'])
            if backend is None or not backend.awake():
                results[copy['backend']] = 'skipped: backend asleep'
                continue
            try:
                backend.json('DELETE', '/api/delete', {'model': model})
                results[copy['backend']] = 'deleted'
            except urllib.error.HTTPError as e:
                results[copy['backend']] = f'error {e.code}'
        self.router.catalog.remove(model)
        self.send_json(200, {'model': model, 'backends': results})

    def passthrough(self, method):
        if not self.path.startswith(PASSTHROUGH_PREFIXES):
            return self.send_json(404, {'error': 'unknown route'})
        body, raw = self.body_json() if method in ('POST', 'DELETE') else ({}, b'')
        backend = self.router.backend_for(body.get('model', ''), body.get('backend')) if isinstance(body, dict) and body.get('model') else None
        backend = backend or self.router.backends[self.router.default_backend]
        if not backend.awake():
            return self.send_json(503, {'error': f'{backend.name} is waking; retry in 10 seconds'})
        return self.forward(backend, method, self.path, raw or None)

    def forward(self, backend, method, path, raw):
        req = urllib.request.Request(backend.url + path, data=raw, headers=backend.headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=600) as upstream:
                data = upstream.read()
                self.send_response(upstream.status)
                self.send_header('Content-Type', upstream.headers.get('Content-Type', 'application/json'))
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            self.send_header('Content-Type', e.headers.get('Content-Type', 'application/json'))
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32


def build(config, catalog, ui_token, kube=None):
    backends = [Backend(spec, kube) for spec in config['backends']]
    return Router(config, catalog, backends, ui_token)


def main():
    config = json.loads(Path('/config/config.json').read_text())
    token = Path('/auth/token').read_text().strip()
    if len(token) < 32:
        raise ValueError('Require an external bearer token of at least 32 characters')
    os.umask(0o077)
    catalog = Catalog('/data/catalog.sqlite')
    try:
        kube = Kubernetes()
    except (OSError, KeyError):
        kube = None
    server = Server(('0.0.0.0', 8080), Handler)
    server.router = build(config, catalog, token, kube)
    server.serve_forever()


if __name__ == '__main__':
    main()
