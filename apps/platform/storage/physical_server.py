"""Unprivileged mTLS exporter serving a separately sampled, read-only snapshot."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import ssl


class CapacityServer(ThreadingHTTPServer):
    """Accept TCP promptly; authenticate with a deadline inside each worker."""
    daemon_threads = True

    def __init__(self, address, handler, context):
        self.context = context
        super().__init__(address, handler)

    def process_request_thread(self, request, client_address):
        try:
            request.settimeout(5)
            request = self.context.wrap_socket(request, server_side=True, do_handshake_on_connect=False)
            request.do_handshake()
            super().process_request_thread(request, client_address)
        except (OSError, ssl.SSLError):
            request.close()


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
    if not any(address in ipaddress.ip_network(cidr) for cidr in
               ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10')):
        raise ValueError('Exporter bind must be a private LAN or Tailscale IPv4 address')
    server = CapacityServer((str(address), 9443), Handler, context)
    server.serve_forever()


if __name__ == '__main__':
    main()
