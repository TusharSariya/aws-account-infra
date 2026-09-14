"""Unprivileged mTLS exporter serving a separately sampled, read-only snapshot."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import ssl


def main():
    config = json.loads(Path('/etc/homelab-capacity/config.json').read_text())

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/capacity':
                self.send_error(404)
                return
            try:
                body = Path('/run/homelab-capacity/sample.json').read_bytes()
                json.loads(body)
            except (OSError, ValueError):
                self.send_error(503, 'Capacity unavailable')
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain('/etc/homelab-capacity/server.crt', '/etc/homelab-capacity/server.key')
    context.load_verify_locations('/etc/homelab-capacity/client-ca.crt')
    context.verify_mode = ssl.CERT_REQUIRED
    address = ipaddress.ip_address(config['bind'])
    if address not in ipaddress.ip_network('100.64.0.0/10'):
        raise ValueError('Exporter bind must be a private Tailscale IPv4 address')
    server = ThreadingHTTPServer((str(address), 9443), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
