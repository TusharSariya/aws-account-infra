"""Opt-in authenticated chat and durable batch gateway; one execution per backend."""

import concurrent.futures
import hmac
import fcntl
import http.client
import socket
from urllib.parse import urlsplit
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from certificates import reconcile_serving
from runtime import Kubernetes, Runtimes
from store import Store, TERMINAL


class Gateway:
    def __init__(self, config, store, runtimes):
        self.config, self.store, self.runtimes = config, store, runtimes
        self.streams = {}
        self.lock = threading.Lock()
        self.pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=len(config["profiles"])
        )
        self.store.recover()
        self.last_healthy = 0

    def validate(self, payload):
        payload = dict(payload)
        if payload.get("model") not in {p["model"] for p in self.config["profiles"]}:
            raise ValueError("Unsupported model")
        messages = payload.get("messages")
        if not isinstance(messages, list) or not 1 <= len(messages) <= 128:
            raise ValueError("messages must contain 1 to 128 entries")
        if any(
            not isinstance(m, dict)
            or m.get("role") not in {"system", "user", "assistant"}
            or not isinstance(m.get("content"), str)
            for m in messages
        ):
            raise ValueError("Only text chat messages are supported")
        maximum = payload.get("max_tokens", 512)
        if (
            isinstance(maximum, bool)
            or not isinstance(maximum, int)
            or not 1 <= maximum <= 4096
        ):
            raise ValueError("max_tokens must be 1 to 4096")
        # Forward a bounded allowlist, never arbitrary backend configuration.
        result = {
            "model": payload["model"],
            "messages": messages,
            "max_tokens": maximum,
            "stream": bool(payload.get("stream", False)),
        }
        if "temperature" in payload:
            value = payload["temperature"]
            if not isinstance(value, (float, int)) or not 0 <= value <= 2:
                raise ValueError("Invalid temperature")
            result["temperature"] = value
        return result

    def run(self):
        while True:
            try:
                reconcile_serving(self.runtimes.kube, self.config["profiles"])
                profiles = self.runtimes.reconcile()
                self.store.fenced_by_reboot(profiles)
                by_id = {p["id"]: p for p in profiles}
                for item in self.store.claim(profiles):
                    self.pool.submit(self.execute, item, by_id[item["backend"]])
                self.last_healthy = time.monotonic()
            except Exception as exc:
                # Do not include request bodies, credentials or HTTP responses in logs.
                print("Reconciliation unavailable: " + type(exc).__name__, flush=True)
            time.sleep(1)

    def emit(self, key, value):
        with self.lock:
            channel = self.streams.get(key)
        if channel:
            channel.put(value, timeout=2)

    def execute(self, item, profile):
        target = urlsplit(profile["url"])
        connection = http.client.HTTPConnection(
            target.hostname, target.port, timeout=10
        )
        wire = None

        def interrupt():
            try:
                if wire is not None:
                    wire.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            if wire is not None:
                wire.close()

        deadline = threading.Timer(self.config.get("executionSeconds", 120), interrupt)
        deadline.daemon = True
        deadline.start()
        started = time.monotonic()
        try:
            connection.connect()
            wire = connection.sock
            connection.request(
                "POST",
                "/v1/chat/completions",
                body=item["payload"].encode(),
                headers={"Content-Type": "application/json"},
            )
            with connection.getresponse() as response:
                if response.status != 200:
                    raise ConnectionError("Backend rejected request")
                if item["stream"]:
                    chunks = []
                    size = 0
                    done = False
                    tail = b""
                    while True:
                        if time.monotonic() - started > self.config.get(
                            "executionSeconds", 120
                        ):
                            raise TimeoutError()
                        chunk = response.read1(65536)
                        if not chunk:
                            break
                        size += len(chunk)
                        if len(chunk) > 65536 or size > 1024 * 1024:
                            raise ValueError("Stream limit")
                        chunks.append(chunk)
                        self.emit(item["id"], chunk)
                        tail = (tail + chunk)[-131072:]
                        if any(
                            line.strip() == b"data: [DONE]"
                            for line in tail.splitlines()
                        ):
                            done = True
                            break
                    if not done:
                        raise ConnectionError("Interrupted stream")
                    result = {"sse": b"".join(chunks).decode()}
                else:
                    data = bytearray()
                    while True:
                        if time.monotonic() - started > self.config.get(
                            "executionSeconds", 120
                        ):
                            raise TimeoutError()
                        chunk = response.read1(65536)
                        if not chunk:
                            break
                        data.extend(chunk)
                        if len(data) > 1024 * 1024:
                            raise ValueError("Result limit")
                    result = json.loads(data)
                self.store.complete(item["id"], item["attempt"], result)
        except urllib.error.HTTPError as exc:
            # An HTTP error is not proof that remote generation terminated.
            self.store.failed(
                item["id"],
                item["attempt"],
                "Backend HTTP " + str(exc.code),
                terminated=False,
            )
        except Exception as exc:
            self.store.failed(
                item["id"], item["attempt"], type(exc).__name__, terminated=False
            )
        finally:
            deadline.cancel()
            connection.close()
            try:
                self.emit(item["id"], None)
            except queue.Full:
                pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass

    @property
    def gateway(self):
        return self.server.gateway

    def send_json(self, code, value):
        data = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        expected = "Bearer " + self.server.token
        if not hmac.compare_digest(self.headers.get("Authorization", ""), expected):
            self.send_json(401, {"error": "Bearer authentication required"})
            return False
        return True

    def do_GET(self):
        if self.path == "/healthz":
            return self.send_json(
                200 if time.monotonic() - self.gateway.last_healthy < 15 else 503,
                {"alive": True},
            )
        if not self.authorized():
            return
        parts = self.path.strip("/").split("/")
        if len(parts) not in {3, 4} or parts[:2] != ["v1", "requests"]:
            return self.send_json(404, {"error": "Unknown endpoint"})
        item = self.gateway.store.get(parts[2])
        if not item:
            return self.send_json(404, {"error": "Unknown request"})
        if len(parts) == 4 and parts[3] == "result":
            return self.send_json(
                200 if item["state"] == "succeeded" else 409,
                json.loads(item["result"])
                if item["result"]
                else {"id": item["id"], "state": item["state"], "error": item["error"]},
            )
        return self.send_json(
            200,
            {
                k: item[k]
                for k in [
                    "id",
                    "state",
                    "policy",
                    "lane",
                    "backend",
                    "attempt",
                    "error",
                ]
            },
        )

    def do_POST(self):
        if not self.authorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536 or self.headers.get("Transfer-Encoding"):
                raise ValueError("Require Content-Length <= 65536")
            raw = json.loads(self.rfile.read(length))
            if not isinstance(raw, dict):
                raise ValueError("Request body must be an object")
            if self.path not in {"/v1/chat/completions", "/v1/requests", "/v1/batches"}:
                return self.send_json(404, {"error": "Unknown endpoint"})
            if self.path == "/v1/batches":
                items = raw.get("requests")
                if not isinstance(items, list) or not 1 <= len(items) <= 64:
                    raise ValueError("Batch size must be 1 to 64")
                results = []
                for entry in items:
                    if not isinstance(entry, dict):
                        results.append({"error": "Batch entry must be an object"})
                        continue
                    try:
                        payload = self.gateway.validate(entry["body"])
                        if payload["stream"]:
                            raise ValueError("Batch streaming is unsupported")
                        item = self.gateway.store.submit(
                            payload,
                            policy=entry.get("policy", "gpu-preferred"),
                            retry_safe=entry.get("retry_safe") is True,
                            request_id=entry["id"],
                        )
                        results.append({"id": item["id"], "state": item["state"]})
                    except (ValueError, KeyError, OverflowError) as exc:
                        results.append({"id": entry.get("id"), "error": str(exc)})
                return self.send_json(207, {"requests": results})
            live = self.path == "/v1/chat/completions"
            payload = self.gateway.validate(raw)
            if payload["stream"] and not live:
                raise ValueError("Streaming requires live endpoint")
            # Register stream channel under the same lock before the worker can emit.
            with self.gateway.lock:
                key = self.headers.get("Idempotency-Key")
                if payload["stream"] and key and self.gateway.store.get(key):
                    return self.send_json(
                        409,
                        {"error": "A stream cannot be replayed or silently restarted"},
                    )
                item = self.gateway.store.submit(
                    payload,
                    policy=raw.get("policy", "gpu-preferred"),
                    lane="live" if live else "batch",
                    stream=payload["stream"],
                    retry_safe=raw.get("retry_safe") is True,
                    request_id=key,
                )
                if payload["stream"]:
                    self.gateway.streams[item["id"]] = queue.Queue(maxsize=64)
            if not live:
                return self.send_json(
                    202, {"id": item["id"], "status_url": "/v1/requests/" + item["id"]}
                )
            self.live(item)
        except OverflowError as exc:
            self.send_json(429, {"error": str(exc)})
        except (ValueError, KeyError, TypeError) as exc:
            self.send_json(400, {"error": str(exc)})

    def live(self, item):
        key = item["id"]
        started = time.monotonic()
        try:
            while item["state"] == "queued" and time.monotonic() - started < 30:
                time.sleep(0.1)
                item = self.gateway.store.get(key)
            if item["state"] in {"queued", "expired"}:
                return self.send_json(
                    504, {"id": key, "error": "Admission exceeded 30 seconds"}
                )
            if item["stream"]:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                with self.gateway.lock:
                    channel = self.gateway.streams[key]
                while (
                    time.monotonic() - started
                    < self.gateway.config.get("executionSeconds", 120) + 40
                ):
                    try:
                        chunk = channel.get(timeout=1)
                    except queue.Empty:
                        continue
                    if chunk is None:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                # An interrupted stream closes without synthesizing [DONE]. Inspect status for uncertainty.
            else:
                while (
                    item["state"] not in TERMINAL | {"uncertain"}
                    and time.monotonic() - started
                    < self.gateway.config.get("executionSeconds", 120) + 40
                ):
                    time.sleep(0.1)
                    item = self.gateway.store.get(key)
                if item["state"] == "succeeded":
                    return self.send_json(200, json.loads(item["result"]))
                return self.send_json(
                    503, {"id": key, "state": item["state"], "error": item["error"]}
                )
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            if item["stream"]:
                with self.gateway.lock:
                    self.gateway.streams.pop(key, None)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, *args):
        try:
            super().process_request_thread(*args)
        finally:
            self.slots.release()


def main():
    config = json.loads(Path("/config/config.json").read_text())
    token = Path("/auth/token").read_text().strip()
    if len(token) < 32:
        raise ValueError("Require an external bearer token of at least 32 characters")
    os.umask(0o077)
    process_lock = open("/data/controller.lock", "a")
    fcntl.flock(process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    store = Store("/data/requests.sqlite", limit=config.get("queueLimit", 1024))
    gateway = Gateway(config, store, Runtimes(Kubernetes(), config, store))
    server = Server(("0.0.0.0", 8080), Handler)
    server.gateway = gateway
    server.token = token
    threading.Thread(target=gateway.run, daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
