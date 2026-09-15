"""An authenticated identity probe does not acquire work or the tracker lock."""
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import re
import secrets
import threading
from urllib.parse import urlsplit, parse_qs


def serve(tracker, address=('0.0.0.0', 7001)):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(2)

        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            challenge = parse_qs(parsed.query).get('challenge', [''])[0]
            if (parsed.path != '/activity-identity' or not re.fullmatch('[a-f0-9]{32}', challenge) or
                    not secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + tracker.token)):
                self.send_error(401)
                return
            signature = hmac.new(tracker.token.encode(), (challenge + ':' + tracker.process).encode(), hashlib.sha256).hexdigest()
            body = json.dumps({'process_id': tracker.process, 'signature': signature}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
    server = HTTPServer(address, Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name='workspace-process-identity').start()
    return server
