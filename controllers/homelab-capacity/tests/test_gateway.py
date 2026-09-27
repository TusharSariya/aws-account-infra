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


def test_cold_page_uses_the_configured_wake_message_and_refreshes_browsers():
    server = gateway(("127.0.0.1", 1))  # nothing listens: always cold
    server.wake_message = "Waking the playground server, about 10 minutes."
    try:
        client = http.client.HTTPConnection(*server.server_address, timeout=8)
        client.request("GET", "/", headers={"Accept": "text/html"})
        result = client.getresponse()
        body = result.read().decode()
        assert result.status == 503
        assert result.getheader("Retry-After") == "10" and result.getheader("Refresh") == "10"
        assert body.startswith("Waking the playground server")
        client.close()
    finally:
        server.shutdown()
        server.server_close()


class FakeHold:
    """In-memory stand-in for the Lease-backed Hold: same status/set/release/expire surface."""

    max_seconds = 43200

    def __init__(self):
        self.held, self.until = False, None

    def status(self):
        return {"held": self.held, "until": self.until if self.held else None}

    def set(self, seconds=None):
        self.held, self.until = True, "2026-09-28T04:00:00+00:00"
        return self.status()

    def release(self):
        self.held, self.until = False, None
        return self.status()


def test_power_page_holds_and_releases_without_touching_the_application_or_activity():
    server = gateway(("127.0.0.1", 1))  # cold backend: any proxied request would 503
    server.hold = FakeHold()
    try:
        client = http.client.HTTPConnection(*server.server_address, timeout=8)
        client.request("GET", "/_power/", headers={"Accept": "text/html"})
        page = client.getresponse()
        body = page.read().decode()
        assert page.status == 200 and "Not held" in body and "12 h max" in body
        client.close()
        client = http.client.HTTPConnection(*server.server_address, timeout=8)
        client.request("POST", "/_power/hold", b"", headers={"Sec-Fetch-Site": "same-origin"})
        redirect = client.getresponse()
        redirect.read()
        assert redirect.status == 303 and redirect.getheader("Location") == "/_power/"
        assert server.hold.held
        client.close()
        client = http.client.HTTPConnection(*server.server_address, timeout=8)
        client.request("GET", "/_power/status")
        status = client.getresponse()
        assert status.status == 200 and status.read() == b'{"held": true, "until": "2026-09-28T04:00:00+00:00"}\n'
        client.close()
        client = http.client.HTTPConnection(*server.server_address, timeout=8)
        client.request("POST", "/_power/release", b"")
        client.getresponse().read()
        assert not server.hold.held
        client.close()
        assert server.activity.begins == 0
    finally:
        server.shutdown()
        server.server_close()


def test_cross_site_power_posts_are_refused_and_unconfigured_hold_is_404():
    server = gateway(("127.0.0.1", 1))
    server.hold = FakeHold()
    try:
        client = http.client.HTTPConnection(*server.server_address, timeout=8)
        client.request("POST", "/_power/hold", b"", headers={"Sec-Fetch-Site": "cross-site"})
        assert client.getresponse().status == 403 and not server.hold.held
        client.close()
        server.hold = None
        client = http.client.HTTPConnection(*server.server_address, timeout=8)
        client.request("GET", "/_power/")
        assert client.getresponse().status == 404
        client.close()
    finally:
        server.shutdown()
        server.server_close()


def test_hold_expires_only_after_its_cap(monkeypatch):
    from homelab_capacity.gateway import Hold

    hold = Hold.__new__(Hold)
    hold.max_seconds = 60
    calls = []
    state = {"labels": {"homelab.tfdraw.dev/power-hold": "true"},
             "annotations": {"homelab.tfdraw.dev/hold-until": "2026-09-27T12:00:00+00:00"}}

    def request(method, body=None):
        calls.append((method, body))
        if method == "PATCH":
            state["labels"].update(body["metadata"].get("labels", {}))
        return {"metadata": state}

    hold._request = request
    monkeypatch.setattr(time, "time", lambda: 1790510400 - 30)  # 2026-09-27T11:59:30Z
    assert hold.expire()["held"]
    monkeypatch.setattr(time, "time", lambda: 1790510400 + 1)
    assert not hold.expire()["held"]
    assert any(m == "PATCH" and b["metadata"]["labels"]["homelab.tfdraw.dev/power-hold"] == "false" for m, b in calls)


def test_hold_also_starts_the_ai_runtime_when_configured(monkeypatch):
    server = gateway(("127.0.0.1", 1))
    server.hold = FakeHold()
    server.hold_starts_ai = True
    calls = []
    monkeypatch.setattr(Handler, "start_ai", lambda self, force=False: calls.append(force))
    try:
        client = http.client.HTTPConnection(*server.server_address, timeout=8)
        client.request("POST", "/_power/hold", b"")
        assert client.getresponse().status == 303
        client.close()
        assert server.hold.held and calls == [True]
        client = http.client.HTTPConnection(*server.server_address, timeout=8)
        client.request("POST", "/_power/release", b"")
        client.getresponse().read()
        client.close()
        assert not server.hold.held and calls == [True]  # release never touches the lifecycle
    finally:
        server.shutdown()
        server.server_close()
