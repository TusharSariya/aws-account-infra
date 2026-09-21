"""Prove post-deletion log search, metrics ingestion, and local firing/resolved delivery."""

import argparse
import base64
import json
import secrets
import time
import urllib.parse
import urllib.request

from common import BASE, PROFILE, identity, kubectl, run


def request(url, data=None):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read() or "{}")


def wait_for(check, timeout=120):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if check():
                return
        except Exception:
            pass
        time.sleep(3)
    raise RuntimeError("Acceptance condition timed out")


def logs():
    identity(admin=True)
    name = "pilot-observe-" + secrets.token_hex(5)
    token = "pilot-observe " + name
    pod = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": "prototype-slot",
            "labels": {
                "monitoring.homelab/pilot-logs": "true",
                "monitoring.homelab/proof": name,
            },
        },
        "spec": {
            "restartPolicy": "Never",
            "nodeSelector": {"node-role.kubernetes.io/control-plane": ""},
            "tolerations": [
                {
                    "key": "node-role.kubernetes.io/control-plane",
                    "operator": "Exists",
                    "effect": "NoSchedule",
                }
            ],
            "automountServiceAccountToken": False,
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 65534,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [
                {
                    "name": "marker",
                    "image": PROFILE["image"],
                    "command": [
                        "sh",
                        "-c",
                        f'echo "{token}"; echo "excluded-payload"; sleep 45',
                    ],
                    "resources": {
                        "requests": {"cpu": "5m", "memory": "8Mi"},
                        "limits": {"cpu": "50m", "memory": "16Mi"},
                    },
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "readOnlyRootFilesystem": True,
                        "capabilities": {"drop": ["ALL"]},
                    },
                }
            ],
        },
    }
    kubectl("create", "-f", "-", admin=True, data=json.dumps(pod))
    query = urllib.parse.urlencode({"query": '{pod="' + name + '"} |= "' + token + '"'})
    url = "http://127.0.0.1:3100/loki/api/v1/query_range?" + query
    try:
        wait_for(lambda: request(url)["data"]["result"])
    finally:
        identity(admin=True)
        kubectl(
            "delete", "pod", name, "-n", "prototype-slot", "--wait=true", admin=True
        )
    wait_for(lambda: request(url)["data"]["result"])
    assert not request(
        "http://127.0.0.1:3100/loki/api/v1/query_range?"
        + urllib.parse.urlencode(
            {"query": '{pod="' + name + '"} |= "excluded-payload"'}
        )
    )["data"]["result"]
    metric = request(
        "http://127.0.0.1:9090/api/v1/query?"
        + urllib.parse.urlencode({"query": "pilot_collection_success"})
    )
    assert metric["data"]["result"][0]["value"][1] == "1"
    print(
        json.dumps(
            {"log_after_deletion": name, "payload_excluded": True, "metrics": True}
        )
    )


def alerts():
    name = "PilotDeliveryTest_" + secrets.token_hex(4)
    receipts = BASE / "data/exporter/notifications.jsonl"
    proof = BASE / "config/proofs/delivery.yml"
    proof.parent.mkdir(exist_ok=True)

    def received(status):
        return receipts.exists() and any(
            a["name"] == name and a["status"] == status
            for line in receipts.read_text().splitlines()
            for a in json.loads(line)["alerts"]
        )

    def reload():
        if (BASE / "kubernetes-mode").exists():
            identity(admin=True)
            contents = proof.read_text() if proof.exists() else '{"groups": []}'
            kubectl(
                "apply",
                "-f",
                "-",
                admin=True,
                data=json.dumps(
                    {
                        "apiVersion": "v1",
                        "kind": "ConfigMap",
                        "metadata": {
                            "name": "delivery-proof",
                            "namespace": "pilot-monitoring",
                        },
                        "data": {"delivery.yml": contents},
                    }
                ),
            )
            # Projected ConfigMap propagation can take two kubelet sync periods.
            time.sleep(130)
            req = urllib.request.Request(
                "http://127.0.0.1:9090/-/reload", data=b"", method="POST"
            )
            with urllib.request.urlopen(req, timeout=15):
                pass
            return
        run(
            [
                "systemctl",
                "--user",
                "kill",
                "--kill-whom=main",
                "--signal=HUP",
                "pilot-prometheus",
            ]
        )

    try:
        proof.write_text(
            json.dumps(
                {
                    "groups": [
                        {
                            "name": "delivery-proof",
                            "rules": [
                                {
                                    "alert": name,
                                    "expr": "vector(1)",
                                    "labels": {"severity": "test"},
                                }
                            ],
                        }
                    ]
                }
            )
        )
        reload()
        wait_for(lambda: received("firing"))
        rule = json.loads(proof.read_text())
        rule["groups"][0]["rules"][0]["expr"] = "vector(0) > 0"
        proof.write_text(json.dumps(rule))
        reload()
        wait_for(lambda: received("resolved"), timeout=180)
    finally:
        proof.unlink(missing_ok=True)
        reload()
    print(
        json.dumps(
            {
                "alert": name,
                "prometheus_evaluated": True,
                "firing": True,
                "resolved": True,
            }
        )
    )


def dashboards():
    password = (BASE / "private/grafana-password").read_text().strip()
    auth = base64.b64encode(("admin:" + password).encode()).decode()

    def grafana(path):
        req = urllib.request.Request(
            "http://127.0.0.1:3000" + path, headers={"Authorization": "Basic " + auth}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)

    wait_for(lambda: grafana("/api/health")["database"] == "ok")
    dashboard = grafana("/api/dashboards/uid/isolated-pilot")
    assert dashboard["meta"]["provisioned"]
    for source in ["pilot-prometheus", "pilot-loki"]:
        wait_for(
            lambda: grafana("/api/datasources/uid/" + source + "/health")["status"]
            == "OK"
        )
    if (BASE / "kubernetes-mode").exists():
        for expr in [
            "pilot_pending_workloads",
            "pilot_controller_up",
            "pilot_worker_paused",
            'pilot_host_memory_bytes{kind="MemAvailable"}',
            'kubelet_volume_stats_capacity_bytes{namespace="pilot-monitoring"}',
        ]:
            url = "http://127.0.0.1:9090/api/v1/query?" + urllib.parse.urlencode(
                {"query": expr}
            )
            wait_for(lambda: bool(request(url)["data"]["result"]))
        volume_url = "http://127.0.0.1:9090/api/v1/query?" + urllib.parse.urlencode(
            {
                "query": 'kubelet_volume_stats_capacity_bytes{namespace="pilot-monitoring"}'
            }
        )
        # Kubelet's volume statistics refresh asynchronously after Pod replacement.
        wait_for(
            lambda: {
                v["metric"]["persistentvolumeclaim"]
                for v in request(volume_url)["data"]["result"]
            }
            == {"prometheus", "loki", "alloy", "grafana", "alertmanager"}
        )
    print(
        json.dumps(
            {
                "dashboard": dashboard["dashboard"]["uid"],
                "panels": len(dashboard["dashboard"]["panels"]),
                "datasources_healthy": True,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["logs", "alerts", "dashboards"])
    args = parser.parse_args()
    {"logs": logs, "alerts": alerts, "dashboards": dashboards}[args.stage]()
