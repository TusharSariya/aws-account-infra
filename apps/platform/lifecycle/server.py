"""Authenticated lifecycle API. No request bodies, tokens or application data are logged."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import threading
import time

from kube import Conflict, Kubernetes, Unavailable
from runtime import Runtime
from state import Rejected


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def respond(self, code, value):
        data = json.dumps(value).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def authorized(self, scope):
        expected = 'Bearer ' + self.server.tokens[scope]
        return hmac.compare_digest(self.headers.get('Authorization', '').encode(), expected.encode())

    def dispatch(self):
        path = self.path.split('/')
        if self.command == 'GET' and self.path == '/healthz':
            self.server.runtime.current_status()
            return self.respond(200, {'ready': True})
        source = path[2] if len(path) == 4 and path[1] == 'activity' else None
        scope = source if source in ('odysseus', 'ollama') else 'operator'
        if not self.authorized(scope):
            return self.respond(401, {'error': 'Authentication required'})
        if self.command == 'GET' and self.path == '/status':
            return self.respond(200, self.server.runtime.current_status())
        if self.command != 'POST':
            return self.respond(404, {'error': 'Unknown operation'})
        length = int(self.headers.get('Content-Length', '0'))
        if not 1 <= length <= 65536 or self.headers.get('Transfer-Encoding'):
            return self.respond(400, {'error': 'Bounded JSON body required'})
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise Rejected('JSON object required')
        if self.path in ('/start', '/stop', '/force-stop'):
            value = self.server.runtime.operate(self.path[1:], payload)
        elif source in ('odysseus', 'ollama'):
            value = self.server.runtime.activity(source, path[3], payload)
        else:
            return self.respond(404, {'error': 'Unknown operation'})
        self.respond(200, value)

    def handle_request(self):
        try:
            self.dispatch()
        except Conflict:
            self.respond(409, {'error': 'State changed; retry the same command ID and revision, or inspect Status before issuing a new command'})
        except Rejected as error:
            self.respond(409, {'error': str(error)})
        except (ValueError, TypeError, KeyError):
            self.respond(400, {'error': 'Invalid request'})
        except Unavailable:
            self.respond(503, {'error': 'Verified lifecycle state is temporarily unavailable'})
        except (OSError, TimeoutError):
            self.close_connection = True

    do_GET = handle_request
    do_POST = handle_request


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32
    slots = threading.BoundedSemaphore(32)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def main():
    config = json.loads(Path('/config/config.json').read_text())
    server = Server(('0.0.0.0', 8080), Handler)
    server.tokens = {name: Path('/credentials/' + name).read_text().strip() for name in ('operator', 'odysseus', 'ollama')}
    if any(len(value) < 43 for value in server.tokens.values()) or len(set(server.tokens.values())) != 3:
        raise ValueError('Separate lifecycle credentials of at least 256 bits are required')
    runtime = Runtime(Kubernetes(), os.environ['POD_UID'], config, source_keys=server.tokens)
    server.runtime = runtime

    def loop():
        while True:
            try:
                runtime.tick()
            except (Conflict, Unavailable, ValueError, KeyError, TypeError):
                runtime.status = None
                runtime.observer.idle_since = None
                print('Lifecycle observation unavailable; admission closed', flush=True)
            time.sleep(2)
    threading.Thread(target=loop, daemon=True).start()
    server.serve_forever()


if __name__ == '__main__':
    main()
