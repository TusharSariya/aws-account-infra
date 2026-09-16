"""Local CONNECT tunnel for the verified Proxmox peer; TLS stays end-to-end."""
import atexit
import select
import socket
import socketserver
import threading
from lifecycle_session import apps


def configure(env):
    hostname = 'pve.tail2f646b.ts.net'
    address = apps.tailnet_ip(hostname)
    class Tunnel(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(10)
            line = self.rfile.readline(4096)
            if line not in (f'CONNECT {hostname}:443 HTTP/1.1\r\n'.encode(),
                            f'CONNECT {hostname}:443 HTTP/1.0\r\n'.encode()):
                self.wfile.write(b'HTTP/1.1 403 Forbidden\r\n\r\n')
                return
            for _ in range(64):
                header = self.rfile.readline(4096)
                if header == b'\r\n': break
                if not header: return
            else: return
            with socket.create_connection((address,443),timeout=10) as remote:
                self.wfile.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
                self.wfile.flush()
                while True:
                    ready,_,_=select.select([self.connection,remote],[],[],60)
                    if not ready: return
                    for source in ready:
                        data=source.recv(65536)
                        if not data:return
                        (remote if source is self.connection else self.connection).sendall(data)
    class Server(socketserver.ThreadingTCPServer):
        daemon_threads=True
    server=Server(('127.0.0.1',0),Tunnel)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    atexit.register(server.server_close)
    env['HTTPS_PROXY']='http://127.0.0.1:'+str(server.server_address[1])
    env['NO_PROXY']='.amazonaws.com,localhost,127.0.0.1,169.254.169.254'
    return server
