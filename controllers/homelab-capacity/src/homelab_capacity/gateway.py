"""Bounded HTTP/WebSocket pass-through with authenticated Kubernetes activity.

No request bodies, headers or URLs are logged. An unavailable backend returns a
retry response before any request bytes are sent upstream. Never replay a request.
"""

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import selectors
import socket
import ssl
import threading
import time
import urllib.request
import uuid


class Activity:
    def __init__(self):
        self.lock = threading.Lock()
        self.active, self.last_activity, self.healthy = 0, 0, False
        self.namespace = os.environ["POD_NAMESPACE"]
        self.name = os.environ["GATEWAY_NAME"]
        self.uid = os.environ["POD_UID"]
        self.context = ssl.create_default_context(
            cafile="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        )
        self.path = (
            "/apis/coordination.k8s.io/v1/namespaces/"
            + self.namespace
            + "/leases/"
            + self.name
        )

    def publish(self):
        with self.lock:
            value = {
                "metadata": {
                    "annotations": {
                        "homelab.tfdraw.dev/active": str(self.active),
                        "homelab.tfdraw.dev/last-activity": str(self.last_activity),
                    }
                },
                "spec": {
                    "holderIdentity": self.uid,
                    "leaseDurationSeconds": 30,
                    "renewTime": datetime.now(timezone.utc).isoformat(),
                },
            }
            token = (
                Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
                .read_text()
                .strip()
            )
            request = urllib.request.Request(
                "https://kubernetes.default.svc" + self.path,
                data=json.dumps(value).encode(),
                method="PATCH",
                headers={
                    "Authorization": "Bearer " + token,
                    "Content-Type": "application/merge-patch+json",
                },
            )
            try:
                with urllib.request.urlopen(
                    request, context=self.context, timeout=3
                ) as response:
                    response.read(65536)
                self.healthy = True
            except Exception:
                self.healthy = False
                raise

    def begin(self):
        with self.lock:
            self.active += 1
            self.last_activity = time.time()
        try:
            self.publish()
        except Exception:
            with self.lock:
                self.active -= 1
            raise

    def finish(self):
        with self.lock:
            self.active -= 1
            self.last_activity = time.time()
        try:
            self.publish()
        except Exception:
            pass  # Stale heartbeat blocks retirement at the coordinator.

    def heartbeat(self, hold=None):
        while True:
            try:
                self.publish()
            except Exception:
                pass
            if hold is not None:
                try:
                    hold.expire()
                except Exception:
                    pass  # The label stays on; the next beat retries.
            time.sleep(5)


class Hold:
    """Owner hold on the durable power-hold Lease the chart renders; expires here, not in the coordinator."""

    def __init__(self, namespace, name, max_seconds):
        self.name = name
        self.max_seconds = max_seconds
        self.context = ssl.create_default_context(
            cafile="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        )
        self.url = (
            "https://kubernetes.default.svc/apis/coordination.k8s.io/v1/namespaces/"
            + namespace
            + "/leases/"
            + name
        )

    def _request(self, method, body=None):
        token = (
            Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
            .read_text()
            .strip()
        )
        headers = {"Authorization": "Bearer " + token}
        if body is not None:
            headers["Content-Type"] = "application/merge-patch+json"
        request = urllib.request.Request(
            self.url,
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers=headers,
        )
        with urllib.request.urlopen(request, context=self.context, timeout=3) as r:
            return json.load(r)

    def status(self):
        """{'held': bool, 'until': iso or None}; the label is the truth the coordinator reads."""
        meta = self._request("GET")["metadata"]
        held = meta.get("labels", {}).get("homelab.tfdraw.dev/power-hold") == "true"
        until = meta.get("annotations", {}).get("homelab.tfdraw.dev/hold-until")
        return {"held": held, "until": until if held else None}

    def set(self, seconds=None):
        seconds = self.max_seconds if seconds is None else min(int(seconds), self.max_seconds)
        until = datetime.fromtimestamp(time.time() + seconds, timezone.utc)
        self._request(
            "PATCH",
            {
                "metadata": {
                    "labels": {"homelab.tfdraw.dev/power-hold": "true"},
                    "annotations": {
                        "homelab.tfdraw.dev/hold-until": until.isoformat(timespec="seconds"),
                        "homelab.tfdraw.dev/hold-set-by": "playground-owner",
                    },
                }
            },
        )
        return self.status()

    def release(self):
        self._request(
            "PATCH",
            {
                "metadata": {
                    "labels": {"homelab.tfdraw.dev/power-hold": "false"},
                    "annotations": {"homelab.tfdraw.dev/hold-until": None},
                }
            },
        )
        return self.status()

    def expire(self):
        """Turn the label off once the cap has passed. Called from the heartbeat; errors are the caller's."""
        current = self.status()
        if not current["held"]:
            return current
        until = current["until"]
        if until is None or datetime.fromisoformat(until).timestamp() <= time.time():
            return self.release()
        return current


HOLD_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Playground power</title>
<style>body{font:18px system-ui,sans-serif;margin:2rem auto;max-width:28rem;padding:0 1rem;color:#eee;background:#111}
button{font:inherit;padding:.8rem 1.4rem;border-radius:.6rem;border:0;margin:.5rem .5rem .5rem 0}
.hold{background:#2d6;color:#031} .release{background:#666;color:#fff} p{line-height:1.5}</style></head>
<body><h1>Playground power</h1>
<p>{status}</p>
<form method="post" action="/_power/hold"><button class="hold">Hold awake ({hours} h max)</button></form>
<form method="post" action="/_power/release"><button class="release">Release</button></form>
<p><a href="/" style="color:#9cf">Back to the playground</a></p>
</body></html>
"""


# Longest silence a bridged connection may sit through before it is cut. Ollama
# streams nothing while it loads a model (60 to 70 s for a 27B GGUF on the CPU
# worker) or evaluates a long prompt (minutes at 7 tokens/s), so this is a dead-
# peer guard, not a request budget; TCP keepalive catches a vanished peer sooner.
BRIDGE_IDLE_SECONDS = 1800
DEFAULT_WAKE_MESSAGE = "Starting the application server. Retry in 10 seconds. Your request has not been replayed."


def bridge(client, upstream):
    """Fixed 64 KiB per-direction queues, preserving upgrade frames and streaming."""
    sockets = [client, upstream]
    buffers = {client: bytearray(), upstream: bytearray()}
    eof = set()
    for sock in sockets:
        sock.setblocking(False)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass
    try:
        with selectors.DefaultSelector() as selector:
            for sock in sockets:
                selector.register(sock, selectors.EVENT_READ)
            while True:
                for sock in sockets:
                    other = upstream if sock is client else client
                    flags = (
                        selectors.EVENT_READ
                        if sock not in eof and len(buffers[other]) < 65536
                        else 0
                    )
                    flags |= selectors.EVENT_WRITE if buffers[sock] else 0
                    try:
                        selector.unregister(sock)
                    except KeyError:
                        pass
                    if flags:
                        selector.register(sock, flags)
                if not selector.get_map():
                    break
                events = selector.select(timeout=BRIDGE_IDLE_SECONDS)
                if not events:
                    break
                for key, flags in events:
                    sock = key.fileobj
                    other = upstream if sock is client else client
                    if flags & selectors.EVENT_READ:
                        data = sock.recv(min(8192, 65536 - len(buffers[other])))
                        if data:
                            buffers[other].extend(data)
                        else:
                            eof.add(sock)
                            # Upstream EOF ends an HTTP response; discard any unread
                            # pipelined client request rather than opening a new route.
                            if sock is upstream:
                                eof.add(client)
                    if flags & selectors.EVENT_WRITE and buffers[sock]:
                        sent = sock.send(buffers[sock])
                        del buffers[sock][:sent]
                if upstream in eof and not buffers[client]:
                    break
    finally:
        client.setblocking(True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    rbufsize = 0  # Header parsing must not consume body or WebSocket frame bytes.

    def log_message(self, *_args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def reply(self, status, text, content_type="text/plain; charset=utf-8"):
        payload = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        if status == 503:
            self.send_header("Retry-After", "10")
            if self.command == "GET" and "text/html" in self.headers.get("Accept", ""):
                self.send_header("Refresh", "10")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)
        self.close_connection = True

    def handle_expect_100(self):
        # Defer the provisional response to the upstream. proxy() first records
        # demand and connects; a cold backend returns 503 without accepting a body.
        return True

    def start_ai(self, force=False):
        if not (force or getattr(self.server, "start_ai", False)):
            return
        token = Path("/wake-credentials/token").read_text().strip()
        base = "http://ai-lifecycle.homelab-platform.svc.cluster.local:8080"
        headers = {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        }
        request = urllib.request.Request(base + "/wake-status", headers=headers)
        with urllib.request.urlopen(request, timeout=3) as response:
            status = json.load(response)
        if status["desired"] != "on":
            payload = {"command_id": str(uuid.uuid4()), "revision": status["revision"]}
            request = urllib.request.Request(
                base + "/wake",
                headers=headers,
                method="POST",
                data=json.dumps(payload).encode(),
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                response.read(65536)

    def power(self):
        """Owner hold page. Never reaches the application and never counts as activity."""
        hold = getattr(self.server, "hold", None)
        path = self.path.split("?", 1)[0]
        if hold is None:
            return self.reply(404, "No hold is configured for this gateway.\n")
        if self.command == "GET" and path == "/_power/status":
            return self.reply(200, json.dumps(hold.status()) + "\n", "application/json")
        if self.command == "POST" and path in ("/_power/hold", "/_power/release"):
            if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
                return self.reply(403, "Cross-site power requests are refused.\n")
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length > 4096:
                return self.reply(413, "Body too large.\n")
            self.rfile.read(length)
            if path == "/_power/hold":
                hold.set()
                if getattr(self.server, "hold_starts_ai", False):
                    try:
                        self.start_ai(force=True)  # "held" means the AI job is up, not just kept up
                    except Exception:
                        pass  # The lease is set; the next chat starts the runtime through the gateway path.
            else:
                hold.release()
            self.send_response(303)
            self.send_header("Location", "/_power/")
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            return
        if self.command in ("GET", "HEAD") and path == "/_power/":
            state = hold.status()
            if state["held"]:
                status = "Held awake until " + state["until"].replace("T", " ").replace("+00:00", " UTC") + ". The server and the AI runtime stay up until then, or until you release."
            else:
                status = "Not held. The model stops after 5 minutes without a chat and the server powers off 5 minutes after that. The next tap wakes it, about 10 minutes."
            page = HOLD_PAGE.replace("{status}", status).replace("{hours}", str(hold.max_seconds // 3600))
            return self.reply(200, page, "text/html; charset=utf-8")
        return self.reply(404, "Unknown power operation.\n")

    def proxy(self):
        self.close_connection = True
        if self.path == "/_power/healthz":
            return self.reply(200 if self.server.activity.healthy else 503, "gateway\n")
        if self.path.split("?", 1)[0].startswith("/_power/"):
            return self.power()
        if not self.path.startswith("/") or self.path.startswith("//"):
            return self.reply(400, "Origin-form request target required.\n")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) > 1 or (lengths and self.headers.get("Transfer-Encoding")):
            return self.reply(400, "Ambiguous request framing.\n")
        if lengths and (not lengths[0].isdigit() or int(lengths[0]) > 1024**3):
            return self.reply(413, "Request body exceeds the 1 GiB streaming limit.\n")
        tracked = (
            not self.server.wake_paths
            or self.path.split("?", 1)[0] in self.server.wake_paths
        )
        acquired = False
        try:
            if tracked:
                self.server.activity.begin()
                acquired = True
            try:
                upstream = socket.create_connection(self.server.backend, timeout=3)
            except OSError:
                try:
                    self.start_ai()
                except Exception:
                    pass  # Never bypass lifecycle/storage checks.
                return self.reply(503, getattr(self.server, "wake_message", DEFAULT_WAKE_MESSAGE) + "\n")
            with upstream:
                # Fixed destination. Preserve end-to-end authentication and upgrades,
                # but don't allow a client-supplied alternate proxy destination.
                upgrade = self.headers.get("Upgrade", "").lower() == "websocket"
                headers = [
                    (k, v)
                    for k, v in self.headers.items()
                    if k.lower()
                    not in {"proxy-authorization", "proxy-connection", "connection"}
                ]
                headers.append(("Connection", "Upgrade" if upgrade else "close"))
                message = self.command + " " + self.path + " HTTP/1.1\r\n"
                message += "".join(k + ": " + v + "\r\n" for k, v in headers) + "\r\n"
                upstream.sendall(message.encode("iso-8859-1"))
                # From here bytes may have reached the application. On failure close
                # the connection; sending/retrying a second request is forbidden.
                bridge(self.connection, upstream)
        except Exception:
            if not acquired:
                self.reply(503, "Activity tracking is unavailable. Retry later.\n")
        finally:
            if acquired:
                self.server.activity.finish()

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = proxy


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(*args, **kwargs)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def main():
    activity = Activity()
    server = Server(("0.0.0.0", 8080), Handler)
    server.activity = activity
    server.backend = (os.environ["UPSTREAM_HOST"], int(os.environ["UPSTREAM_PORT"]))
    server.start_ai = os.environ.get("START_AI") == "true"
    server.wake_paths = set(filter(None, os.environ.get("WAKE_PATHS", "").split(",")))
    server.wake_message = os.environ.get("WAKE_MESSAGE") or DEFAULT_WAKE_MESSAGE
    server.hold = None
    if os.environ.get("HOLD_LEASE"):
        server.hold = Hold(
            os.environ["HOLD_NAMESPACE"],
            os.environ["HOLD_LEASE"],
            int(os.environ.get("HOLD_MAX_SECONDS", "43200")),
        )
        server.hold_starts_ai = os.environ.get("HOLD_STARTS_AI") == "true"
    threading.Thread(target=activity.heartbeat, args=(server.hold,), daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
