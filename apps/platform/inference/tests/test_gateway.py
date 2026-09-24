import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from gateway import Gateway, Handler, Server
from store import Store
import urllib.request
import urllib.error
import pytest


class Backend(BaseHTTPRequestHandler):
    mode = "success"

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.end_headers()
        if self.mode == "stream":
            self.wfile.write(b'data: {"text":"hello"}\n\ndata: [DONE]\n\n')
        elif self.mode == "broken":
            self.wfile.write(b'data: {"text":"hello"}\n\n')
        else:
            self.wfile.write(b'{"choices":[{"message":{"content":"hello"}}]}')


@pytest.mark.parametrize(
    "mode,state",
    [("success", "succeeded"), ("stream", "succeeded"), ("broken", "uncertain")],
)
def test_backend_completion_and_interrupted_stream(tmp_path, mode, state):
    class Fixture(Backend):
        pass

    Fixture.mode = mode
    server = HTTPServer(("127.0.0.1", 0), Fixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    store = Store(tmp_path / "db")
    gateway = Gateway({"profiles": [{"model": "qwen"}]}, store, None)
    item = store.submit(
        {"model": "qwen", "messages": [{"role": "user", "content": "hi"}]},
        lane="live",
        stream=mode != "success",
        retry_safe=True,
    )
    profile = {
        "id": "cpu",
        "kind": "cpu",
        "priority": 1,
        "model": "qwen",
        "healthy": True,
        "generation": "node/boot/pod",
        "url": f"http://127.0.0.1:{server.server_port}",
    }
    item = store.claim([profile])[0]
    gateway.execute(item, profile)
    assert store.get(item["id"])["state"] == state
    assert store.get(item["id"])["attempt"] == 1
    server.shutdown()
    server.server_close()
    gateway.pool.shutdown()


def test_durable_http_submission_authentication_idempotency_and_results(tmp_path):
    store = Store(tmp_path / "db")
    gateway = Gateway({"profiles": [{"model": "qwen"}]}, store, None)
    server = Server(("127.0.0.1", 0), Handler)
    server.gateway = gateway
    server.token = "x" * 32
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def request(path, body=None, auth=True):
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}" + path,
            data=json.dumps(body).encode() if body else None,
            headers={
                "Authorization": "Bearer " + server.token if auth else "",
                "Idempotency-Key": "durable",
            },
        )
        with urllib.request.urlopen(req, timeout=2) as response:
            return json.load(response)

    payload = {
        "model": "qwen",
        "messages": [{"role": "user", "content": "hi"}],
        "policy": "gpu-required",
    }
    with pytest.raises(urllib.error.HTTPError) as exc:
        request("/v1/requests", payload, auth=False)
    assert exc.value.code == 401
    assert request("/v1/requests", payload)["id"] == "durable"
    assert request("/v1/requests", payload)["id"] == "durable"
    assert request("/v1/requests/durable")["state"] == "queued"
    assert request("/v1/requests/durable")["policy"] == "gpu-required"
    store.claim(
        [
            dict(
                id="gpu",
                kind="gpu",
                priority=0,
                model="qwen",
                healthy=True,
                generation="node/boot/pod",
            )
        ]
    )
    store.complete("durable", 1, {"answer": "persisted"})
    assert request("/v1/requests/durable/result") == {"answer": "persisted"}
    server.shutdown()
    server.server_close()
    gateway.pool.shutdown()
