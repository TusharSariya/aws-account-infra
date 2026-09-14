"""A silent TCP peer must not prevent an authenticated capacity request."""
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'apps/platform/storage'))
from physical_server import CapacityServer


class ServerTests(unittest.TestCase):
    def test_stalled_handshake_does_not_block_authenticated_request(self):
        with tempfile.TemporaryDirectory() as directory:
            cert, key = [str(Path(directory) / name) for name in ('cert.pem', 'key.pem')]
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                '-keyout', key, '-out', cert, '-days', '1', '-subj', '/CN=localhost',
                '-addext', 'subjectAltName=DNS:localhost'], check=True, capture_output=True)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            context.load_verify_locations(cert)
            context.verify_mode = ssl.CERT_REQUIRED
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'capacity-ok')
                def log_message(self, *_args):
                    pass
            server = CapacityServer(('127.0.0.1', 0), Handler, context)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with socket.create_connection(server.server_address, timeout=2) as stalled:
                    client = ssl.create_default_context(cafile=cert)
                    client.load_cert_chain(cert, key)
                    with client.wrap_socket(socket.create_connection(server.server_address, timeout=2),
                                            server_hostname='localhost') as connection:
                        connection.sendall(b'GET /capacity HTTP/1.0\r\n\r\n')
                        response = b''
                        while chunk := connection.recv(4096):
                            response += chunk
                        self.assertIn(b'capacity-ok', response)
                    self.assertIsNotNone(stalled.fileno())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
