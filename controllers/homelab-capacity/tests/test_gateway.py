from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import socket
import pytest
import threading
import time
from homelab_capacity.gateway import Server, Handler


class Activity:
    healthy = True

    def __init__(self):
        self.active = self.begins = 0

    def begin(self):
        self.active += 1
        self.begins += 1

    def finish(self):
        self.active -= 1


def gateway(backend):
    server = Server(("127.0.0.1", 0), Handler)
    server.activity = Activity()
    server.backend = backend
    server.wake_paths = set()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_cold_post_gets_retry_without_replay():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    address = probe.getsockname()
    server = gateway(address)
    try:
        client = http.client.HTTPConnection(*server.server_address, timeout=8)
        client.request("POST", "/submit", b"private-body")
        response = client.getresponse()
        assert response.status == 503 and response.getheader("Retry-After") == "10"
        assert b"private-body" not in response.read()
        assert server.activity.begins == 1
        client.close()
    finally:
        probe.close()
        server.shutdown()
        server.server_close()


def test_http_post_auth_and_response_stream_are_preserved_once():
    received = []

    class Backend(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(
                (
                    self.headers.get("Authorization"),
                    self.rfile.read(int(self.headers["Content-Length"])),
                )
            )
            self.send_response(200)
            self.send_header("Content-Length", "6")
            self.end_headers()
            self.wfile.write(b"result")

        def log_message(self, *_args):
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    server = gateway(backend.server_address)
    try:
        client = http.client.HTTPConnection(*server.server_address, timeout=8)
        client.request("POST", "/submit", b"body", {"Authorization": "Bearer fixture"})
        result = client.getresponse()
        assert result.status == 200 and result.read() == b"result"
        assert received == [("Bearer fixture", b"body")]
        client.close()
    finally:
        server.shutdown()
        server.server_close()
        backend.shutdown()
        backend.server_close()


def test_health_checks_do_not_generate_demand():
    server = gateway(("127.0.0.1", 1))
    try:
        client = http.client.HTTPConnection(*server.server_address, timeout=8)
        client.request("GET", "/_power/healthz")
        assert client.getresponse().status == 200
        assert server.activity.begins == 0
        client.close()
    finally:
        server.shutdown()
        server.server_close()


def test_cold_expect_upload_records_demand_without_accepting_body():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    server = gateway(probe.getsockname())
    try:
        with socket.create_connection(server.server_address, timeout=8) as client:
            client.sendall(
                b"POST /upload HTTP/1.1\r\nHost: fixture\r\nExpect: 100-continue\r\nContent-Length: 100\r\n\r\n"
            )
            response = client.recv(4096)
            assert response.startswith(b"HTTP/1.1 503")
            assert server.activity.begins == 1
    finally:
        probe.close()
        server.shutdown()
        server.server_close()


def test_websocket_upgrade_and_early_frame_are_preserved():
    received = []
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    def backend():
        conn, _ = listener.accept()
        with conn:
            data = b""
            while b"\r\n\r\n" not in data:
                data += conn.recv(1)
            received.append(data)
            conn.sendall(
                b"HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n"
            )
            frame = conn.recv(6)
            received.append(frame)
            conn.sendall(frame)

    thread = threading.Thread(target=backend, daemon=True)
    thread.start()
    server = gateway(listener.getsockname())
    try:
        with socket.create_connection(server.server_address, timeout=8) as client:
            frame = b"\x81\x04test"
            client.sendall(
                b"GET /ws HTTP/1.1\r\nHost: fixture\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nAuthorization: Bearer fixture\r\n\r\n"
                + frame
            )
            response = b""
            while not response.endswith(frame):
                response += client.recv(4096)
            assert response.startswith(b"HTTP/1.1 101")
            assert b"Authorization: Bearer fixture" in received[0]
            assert received[1] == frame
        thread.join(2)
    finally:
        listener.close()
        server.shutdown()
        server.server_close()


def test_bridge_idle_guard_outlives_a_silent_model_load(monkeypatch):
    """A cold Ollama load sends nothing for over a minute; the bridge must wait it out."""
    from homelab_capacity import gateway as module

    assert module.BRIDGE_IDLE_SECONDS >= 600

    class Backend(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            time.sleep(0.6)  # silence longer than the shrunken guard below
            self.send_response(200)
            self.send_header("Content-Length", "5")
            self.end_headers()
            self.wfile.write(b"token")

        def log_message(self, *_args):
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    server = gateway(backend.server_address)
    try:
        monkeypatch.setattr(module, "BRIDGE_IDLE_SECONDS", 0.2)
        client = http.client.HTTPConnection(*server.server_address, timeout=8)
        client.request("POST", "/api/generate", b"{}")
        with pytest.raises((http.client.RemoteDisconnected, ConnectionError)):
            client.getresponse()
        client.close()
        monkeypatch.setattr(module, "BRIDGE_IDLE_SECONDS", 5)
        client = http.client.HTTPConnection(*server.server_address, timeout=8)
        client.request("POST", "/api/generate", b"{}")
        result = client.getresponse()
        assert result.status == 200 and result.read() == b"token"
        client.close()
    finally:
        server.shutdown()
        server.server_close()
        backend.shutdown()
        backend.server_close()
