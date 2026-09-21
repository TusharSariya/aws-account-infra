"""Small metadata-only pilot exporter and local notification receipt endpoint."""

import json
import os
import hmac
import re
import ssl
import urllib.request
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from common import BASE, CONTROLLERS, PROFILE, get, identity, memory, run, vmstat

KUBERNETES = (BASE / "kubernetes-mode").exists()

BUCKETS = [1, 5, 10, 30, 60, 120, 300, 900, float("inf")]


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def admitted_delay(workload):
    for condition in workload.get("status", {}).get("conditions", []):
        if condition["type"] == "Admitted" and condition["status"] == "True":
            return max(
                0,
                timestamp(condition["lastTransitionTime"])
                - timestamp(workload["metadata"]["creationTimestamp"]),
            )
    return None


def worker_state(state, nodes):
    paused = (state / "maintenance").exists()
    desired = json.loads((state / "desired.json").read_text())["target"]
    observed = json.loads((state / "observed.json").read_text())
    ready = any(
        n["metadata"]["name"] == observed.get("name")
        and any(
            c["type"] == "Ready" and c["status"] == "True"
            for c in n["status"].get("conditions", [])
        )
        for n in nodes
    )
    return paused, desired, ready, observed.get("name", "")


class Collector:
    def __init__(self):
        self.text = "pilot_collection_success 0\n"
        self.seen = {}
        self.hist = [0] * len(BUCKETS)
        self.total = 0
        self.previous = {}
        self.transitions = {}

    def collect(self):
        lines = []

        def emit(name, value, **labels):
            suffix = (
                "{"
                + ",".join(f"{k}={json.dumps(str(v))}" for k, v in labels.items())
                + "}"
                if labels
                else ""
            )
            lines.append(f"pilot_{name}{suffix} {float(value)}")

        for key in ["MemAvailable", "SwapFree", "SwapTotal"]:
            emit("host_memory_bytes", memory()[key], kind=key)
        for key in ["pswpin", "pswpout"]:
            emit("host_swap_pages_total", vmstat()[key], direction=key)
        disk = os.statvfs(BASE)
        emit("host_disk_free_bytes", disk.f_bavail * disk.f_frsize)
        for name in [
            "prometheus",
            "loki",
            "alloy",
            "exporter",
            "grafana",
            "alertmanager",
        ]:
            directory = BASE / "data" / name
            size = (
                sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())
                if directory.exists()
                else 0
            )
            emit("data_bytes", size, service=name)
            # Retention is not a hard filesystem quota. Stop only this new writer
            # at its disk budget; never prune data or stop an existing controller.
            budget = {
                "loki": 2,
                "prometheus": 2,
                "alloy": 0.25,
                "grafana": 0.5,
                "alertmanager": 0.125,
            }.get(name)
            if (
                not KUBERNETES
                and budget
                and (
                    size >= budget * 1024**3
                    or disk.f_bavail * disk.f_frsize < 5 * 1024**3
                )
            ):
                run(["systemctl", "--user", "stop", "pilot-" + name])
        for unit in CONTROLLERS + (
            ["pilot-exporter"]
            if KUBERNETES
            else [
                "pilot-" + name
                for name in [
                    "prometheus",
                    "loki",
                    "alloy",
                    "exporter",
                    "grafana",
                    "alertmanager",
                ]
            ]
        ):
            properties = dict(
                line.split("=", 1)
                for line in run(
                    [
                        "systemctl",
                        "--user",
                        "show",
                        unit,
                        "-p",
                        "ActiveState",
                        "-p",
                        "NRestarts",
                        "-p",
                        "MemoryCurrent",
                        "-p",
                        "CPUUsageNSec",
                    ]
                ).splitlines()
            )
            emit(
                "controller_up" if unit in CONTROLLERS else "monitoring_up",
                properties["ActiveState"] == "active",
                unit=unit,
            )
            emit(
                "controller_restarts_total"
                if unit in CONTROLLERS
                else "monitoring_restarts_total",
                int(properties.get("NRestarts") or 0),
                unit=unit,
            )
            cpu = properties.get("CPUUsageNSec", "0")
            emit(
                "controller_cpu_seconds_total"
                if unit in CONTROLLERS
                else "monitoring_cpu_seconds_total",
                int(cpu) / 1e9 if cpu.isdigit() else 0,
                unit=unit,
            )
            mem = properties.get("MemoryCurrent", "0")
            emit(
                "controller_memory_bytes"
                if unit in CONTROLLERS
                else "monitoring_memory_bytes",
                int(mem) if mem.isdigit() else 0,
                unit=unit,
            )
        try:
            identity()
            if KUBERNETES:
                for pod in get("pods", "-n", "pilot-monitoring")["items"]:
                    name = pod["metadata"].get("labels", {}).get("app")
                    if name not in [
                        "prometheus",
                        "loki",
                        "alloy",
                        "grafana",
                        "alertmanager",
                    ]:
                        continue
                    emit(
                        "monitoring_up",
                        any(
                            c["type"] == "Ready" and c["status"] == "True"
                            for c in pod["status"].get("conditions", [])
                        ),
                        unit="pilot-" + name,
                    )
                    emit(
                        "monitoring_restarts_total",
                        sum(
                            c.get("restartCount", 0)
                            for c in pod["status"].get("containerStatuses", [])
                        ),
                        unit="pilot-" + name,
                    )
            for ns, name in [
                ("kueue-system", "prototype-kueue-controller-manager"),
                ("prototype-slot", "prototype-binpack"),
                ("prototype-slot", "prototype-slot-ca"),
            ]:
                deployment = get("deployment", name, "-n", ns)
                emit(
                    "kubernetes_controller_available",
                    deployment.get("status", {}).get("availableReplicas", 0),
                    controller=name,
                )
            nodes = get("nodes")["items"]
            emit(
                "nodes_ready",
                sum(
                    any(
                        c["type"] == "Ready" and c["status"] == "True"
                        for c in n["status"]["conditions"]
                    )
                    for n in nodes
                ),
            )
            for slot, config in PROFILE["slots"].items():
                paused, desired, ready, name = worker_state(
                    Path(config["state"]).expanduser(), nodes
                )
                for metric, value in [
                    ("paused", paused),
                    ("desired", desired),
                    ("ready", ready),
                ]:
                    emit("worker_" + metric, value, slot=slot)
                current = (desired, name, ready)
                prev = self.previous.get(slot)
                counters = self.transitions.setdefault(slot, [0, 0])
                if prev:
                    if ready and (not prev[2] or name != prev[1]):
                        counters[0] += 1
                    if desired == 0 and prev[0] != 0:
                        counters[1] += 1
                self.previous[slot] = current
                emit("worker_ready_transitions_total", counters[0], slot=slot)
                emit("worker_retirement_requests_total", counters[1], slot=slot)
            for namespace in ["prototype-slot", "pilot-app"]:
                pods = get("pods", "-n", namespace)["items"]
                for phase in ["Pending", "Running", "Succeeded", "Failed"]:
                    emit(
                        "pods",
                        sum(p["status"].get("phase") == phase for p in pods),
                        namespace=namespace,
                        phase=phase,
                    )
                if namespace == "prototype-slot":
                    workloads = get("workloads.kueue.x-k8s.io", "-n", namespace)[
                        "items"
                    ]
                    pending = 0
                    for w in workloads:
                        delay = admitted_delay(w)
                        finished = any(
                            c["type"] == "Finished" and c["status"] == "True"
                            for c in w.get("status", {}).get("conditions", [])
                        )
                        if delay is None and not finished:
                            pending += 1
                        uid = w["metadata"]["uid"]
                        if delay is not None and uid not in self.seen:
                            self.seen[uid] = time.time()
                            self.hist = [
                                v + int(delay <= b) for v, b in zip(self.hist, BUCKETS)
                            ]
                            self.total += delay
                        if delay is not None:
                            self.seen[uid] = time.time()
                    emit("pending_workloads", pending)
            self.seen = {k: v for k, v in self.seen.items() if v > time.time() - 172800}
            emit("admission_delay_seconds_sum", self.total)
            emit("admission_delay_seconds_count", self.hist[-1])
            for bucket, count in zip(BUCKETS, self.hist):
                emit(
                    "admission_delay_seconds_bucket",
                    count,
                    le="+Inf" if bucket == float("inf") else bucket,
                )
            emit("collection_timestamp_seconds", time.time())
            emit("collection_success", 1)
        except Exception as error:
            # Do not export API error bodies or any workload payload.
            print(type(error).__name__, flush=True)
            emit("collection_success", 0)
        self.text = "\n".join(lines) + "\n"

    def loop(self):
        while True:
            try:
                self.collect()
            except Exception as error:
                self.text = "pilot_collection_success 0\n"
                print(type(error).__name__, flush=True)
            time.sleep(15)


def forward_journal():
    """Commit the cursor only after delivery. Never forward journal message bodies."""
    cursor = BASE / "data/exporter/journal.cursor"
    while True:
        try:
            args = ["journalctl", "--user", "--no-pager", "-o", "json", "-n", "200"]
            for unit in CONTROLLERS:
                args += ["-u", unit]
            if cursor.exists():
                args += ["--after-cursor", cursor.read_text()]
            else:
                args += ["--since", "-2 minutes"]
            entries = [json.loads(line) for line in run(args).splitlines()]
            if entries:
                streams = []
                for entry in entries:
                    phase = re.search(
                        r"ready|retiring|retired|paused|error|failed|No route to host",
                        entry.get("MESSAGE", ""),
                    )
                    unit = entry.get("_SYSTEMD_USER_UNIT", "").removesuffix(".service")
                    if unit not in CONTROLLERS:
                        continue
                    streams.append(
                        {
                            "stream": {"service": unit},
                            "values": [
                                [
                                    str(int(entry["__REALTIME_TIMESTAMP"]) * 1000),
                                    "controller-event "
                                    + (phase.group() if phase else "other"),
                                ]
                            ],
                        }
                    )
                req = urllib.request.Request(
                    "http://127.0.0.1:3100/loki/api/v1/push",
                    data=json.dumps({"streams": streams}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10):
                    pass
                cursor.write_text(entries[-1]["__CURSOR"])
        except Exception as error:
            print("journal-forward: " + type(error).__name__, flush=True)
        time.sleep(15)


class Handler(BaseHTTPRequestHandler):
    def authorized(self):
        if not KUBERNETES:
            return True
        expected = "Bearer " + (BASE / "private/host-token").read_text().strip()
        if hmac.compare_digest(self.headers.get("Authorization", ""), expected):
            return True
        self.send_error(401)
        return False

    def do_GET(self):
        if not self.authorized():
            return
        if self.path != "/metrics":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(self.server.collector.text.encode())

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != "/alerts":
            self.send_error(404)
            return
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 65536:
            self.send_error(413)
            return
        data = json.loads(self.rfile.read(size))
        dest = BASE / "data/exporter/notifications.jsonl"
        # Bound the local receipt journal independently of journald.
        if dest.exists() and dest.stat().st_size > 1024 * 1024:
            dest.replace(dest.with_suffix(".previous"))
        with dest.open("a") as f:
            f.write(
                json.dumps(
                    {
                        "time": time.time(),
                        "status": data.get("status"),
                        "alerts": [
                            {
                                "name": a.get("labels", {}).get("alertname"),
                                "status": a.get("status"),
                            }
                            for a in data.get("alerts", [])
                        ],
                    }
                )
                + "\n"
            )
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("10.0.2.2" if KUBERNETES else "127.0.0.1", 9810), Handler)
    server.timeout = 10
    if KUBERNETES:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(BASE / "private/host.crt", BASE / "private/host.key")
        server.socket = context.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=forward_journal, daemon=True).start()
    server.collector = Collector()
    threading.Thread(target=server.collector.loop, daemon=True).start()
    server.serve_forever()
