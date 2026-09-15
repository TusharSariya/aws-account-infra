"""Disposable image-test controller. Never used by the deployed platform."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path

calls = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.headers.get('Authorization') != 'Bearer ' + Path('/fixture/lifecycle-token').read_text():
            self.send_error(401)
            return
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert body['pod_uid'] == 'disposable-workspace'
        assert len(body['process_id']) == 32
        calls.append(self.path)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{}')

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(calls).encode())


HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
