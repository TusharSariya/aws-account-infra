#!/usr/bin/env python3
"""Live monitoring acceptance using isolated canaries, with no application changes.
Run on the laptop after monitoring rollout; worker restart proof remains separate.
"""

import argparse
import base64
import json
import secrets
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LOCAL_KUBECTL = Path.home() / ".local/share/main-control-plane/private/kubectl"
KUBECTL = str(LOCAL_KUBECTL) if LOCAL_KUBECTL.exists() else "kubectl"

BUSYBOX = "docker.io/library/busybox:1.37.0@sha256:9db7b59979c38555a39def84a31fb98b5296952f9e3afd4f6f11f05b07adfab0"


def request(port, path, data=None, headers=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}" + path,
        data=None if data is None else json.dumps(data).encode(),
        headers=headers or {},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def wait(check, seconds=180):
    end = time.monotonic() + seconds
    last = None
    while time.monotonic() < end:
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
            last = exc
        time.sleep(5)
    raise RuntimeError(f"Acceptance check timed out: {last}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=False, mode=0o700)
    k = [
        KUBECTL,
        "--kubeconfig",
        args.kubeconfig,
        "--server=https://10.0.0.231:6443",
        "--request-timeout=30s",
        "-n",
        "monitoring",
    ]

    def kubectl(*params):
        return subprocess.check_output(k + list(params), text=True)

    name = "main-accept-" + secrets.token_hex(5)
    before = json.loads(kubectl("get", "pvc", "-o", "json"))
    processes = []
    original = None
    extra = None
    log = (args.evidence / "port-forwards.log").open("w")
    result = {"component": "monitoring-smoke", "passed": False, "canary": name}
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": "monitoring"},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {
                    "labels": {"app": name, "monitoring.homelab/main-logs": "true"}
                },
                "spec": {
                    "automountServiceAccountToken": False,
                    "nodeSelector": {"homelab.tfdraw.dev/worker-role": "primary"},
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 65534,
                        "runAsGroup": 65534,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "canary",
                            "image": BUSYBOX,
                            "command": [
                                "sh",
                                "-c",
                                f"echo UNSANITIZED_{name}; while true; do echo main-observe {name}; sleep 5; done",
                            ],
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "resources": {
                                "requests": {"cpu": "10m", "memory": "16Mi"},
                                "limits": {"cpu": "50m", "memory": "32Mi"},
                            },
                        }
                    ],
                },
            },
        },
    }
    try:
        for service, local, remote in [
            ("prometheus", 19090, 9090),
            ("loki", 13100, 3100),
            ("grafana", 13000, 3000),
            ("alertmanager", 19093, 9093),
        ]:
            processes.append(
                subprocess.Popen(
                    k
                    + [
                        "port-forward",
                        "--address=127.0.0.1",
                        "service/" + service,
                        f"{local}:{remote}",
                    ],
                    stdout=log,
                    stderr=log,
                )
            )
        wait(lambda: request(19090, "/api/v1/query?query=up")["status"] == "success")
        targets = request(19090, "/api/v1/targets")["data"]["activeTargets"]
        assert all(
            t["health"] == "up"
            for t in targets
            if t["labels"].get("job") == "monitoring"
        ), targets
        password = base64.b64decode(
            json.loads(kubectl("get", "secret", "grafana-admin", "-o", "json"))["data"][
                "password"
            ]
        ).decode()
        auth = {
            "Authorization": "Basic "
            + base64.b64encode(("admin:" + password).encode()).decode()
        }
        dashboard = request(13000, "/api/dashboards/uid/main-platform", headers=auth)[
            "dashboard"
        ]
        for panel in dashboard["panels"]:
            if panel["title"] == "Active alerts":
                continue
            for target in panel["targets"]:
                query = urllib.parse.urlencode({"query": target["expr"]})
                assert request(19090, "/api/v1/query?" + query)["data"]["result"], (
                    panel["title"]
                )
        subprocess.run(
            k + ["create", "-f", "-"],
            input=json.dumps(deployment),
            text=True,
            check=True,
        )
        kubectl("rollout", "status", "deployment/" + name, "--timeout=180s")

        def logs(token):
            query = urllib.parse.urlencode(
                {"query": '{namespace="monitoring"} |= "' + token + '"', "limit": "100"}
            )
            return request(13100, "/loki/api/v1/query_range?" + query)["data"]["result"]

        wait(lambda: logs(name))
        assert not logs("UNSANITIZED_" + name), "Unsanitized payload reached Loki"
        pod = json.loads(kubectl("get", "pods", "-l", "app=" + name, "-o", "json"))[
            "items"
        ][0]
        kubectl("delete", "pod", pod["metadata"]["name"], "--wait=true")
        wait(
            lambda: any(
                p["metadata"]["uid"] != pod["metadata"]["uid"]
                and p.get("status", {}).get("phase") == "Running"
                for p in json.loads(
                    kubectl("get", "pods", "-l", "app=" + name, "-o", "json")
                )["items"]
            )
        )
        wait(lambda: len(logs(name)) >= 2)
        # Exercise the actual Prometheus -> Alertmanager path with an owned temporary rule.
        cm = json.loads(kubectl("get", "configmap", "prometheus", "-o", "json"))
        original = cm["data"]["alerts.yml"]
        extra = (
            "\n  - name: "
            + name
            + "\n    rules:\n      - alert: MainAcceptance\n        expr: vector(1)\n        labels: {acceptance: "
            + name
            + "}\n"
        )
        patch = {"data": {"alerts.yml": original + extra}}
        kubectl(
            "patch", "configmap", "prometheus", "--type=merge", "-p", json.dumps(patch)
        )
        # No lifecycle endpoint is exposed; Pod restart loads the mounted rule file.
        kubectl("rollout", "restart", "deployment/prometheus")
        kubectl("rollout", "status", "deployment/prometheus", "--timeout=180s")
        wait(
            lambda: any(
                a["labels"].get("acceptance") == name
                for a in request(19093, "/api/v2/alerts")
            ),
            seconds=300,
        )
        kubectl(
            "patch",
            "configmap",
            "prometheus",
            "--type=merge",
            "-p",
            json.dumps({"data": {"alerts.yml": original}}),
        )
        kubectl("rollout", "restart", "deployment/prometheus")
        kubectl("rollout", "status", "deployment/prometheus", "--timeout=180s")
        wait(
            lambda: (
                not any(
                    a["labels"].get("acceptance") == name
                    for a in request(19093, "/api/v2/alerts")
                )
            ),
            seconds=600,
        )
        after = json.loads(kubectl("get", "pvc", "-o", "json"))

        def mapping(obj):
            return {
                x["metadata"]["name"]: (
                    x["metadata"]["uid"],
                    x["spec"].get("volumeName"),
                )
                for x in obj["items"]
            }

        assert mapping(before) == mapping(after)
        result.update(
            passed=True,
            log_marker=name,
            pvc_bindings=mapping(after),
            completed=datetime.now(timezone.utc).isoformat(),
        )
    finally:
        # Delete only the generated canary. No PVCs or existing workload deletion.
        subprocess.run(
            k + ["delete", "deployment", name, "--ignore-not-found"], check=False
        )
        # Restore only this run's rule edit; never overwrite a concurrent rule change.
        if original is not None and extra is not None:
            current = json.loads(
                kubectl("get", "configmap", "prometheus", "-o", "json")
            )
            if current["data"]["alerts.yml"] == original + extra:
                kubectl(
                    "patch",
                    "configmap",
                    "prometheus",
                    "--type=json",
                    "-p",
                    json.dumps(
                        [
                            {
                                "op": "test",
                                "path": "/data/alerts.yml",
                                "value": original + extra,
                            },
                            {
                                "op": "replace",
                                "path": "/data/alerts.yml",
                                "value": original,
                            },
                        ]
                    ),
                )
                kubectl("rollout", "restart", "deployment/prometheus")
        for proc in processes:
            proc.terminate()
            proc.wait(timeout=15)
        log.close()
        (args.evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        "Monitoring smoke passed; capacity and worker-restart persistence still required"
    )


if __name__ == "__main__":
    main()
