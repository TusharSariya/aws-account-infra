#!/usr/bin/env python3
"""Read-only cluster checks using one explicitly created, temporary CP DNS probe.
Run `prepare` before maintenance, `check` throughout it, then `cleanup` afterward.
"""

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

NS = "main-recovery-check"
IMAGE = "docker.io/library/busybox:1.37.0@sha256:9db7b59979c38555a39def84a31fb98b5296952f9e3afd4f6f11f05b07adfab0"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "check", "cleanup"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    base = Path.home() / ".local/share/main-control-plane/private"
    k = [
        str(base / "kubectl"),
        "--kubeconfig",
        str(base / "kubeconfig"),
        "--request-timeout=20s",
    ]

    def call(*cmd):
        return subprocess.check_output(k + list(cmd), text=True)

    if args.action == "prepare":
        assert not call(
            "get", "namespace", NS, "--ignore-not-found", "-o", "name"
        ).strip(), "Probe namespace already exists"
        ns = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": NS,
                "labels": {
                    "pod-security.kubernetes.io/enforce": "restricted",
                    "main-control-plane-probe": "true",
                },
            },
        }
        pod = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "dns", "namespace": NS},
            "spec": {
                "nodeName": "talos-cp-01",
                "automountServiceAccountToken": False,
                "tolerations": [
                    {
                        "key": "node-role.kubernetes.io/control-plane",
                        "operator": "Exists",
                        "effect": "NoSchedule",
                    }
                ],
                "securityContext": {
                    "runAsNonRoot": True,
                    "runAsUser": 65534,
                    "seccompProfile": {"type": "RuntimeDefault"},
                },
                "containers": [
                    {
                        "name": "dns",
                        "image": IMAGE,
                        "command": ["sleep", "86400"],
                        "resources": {
                            "requests": {"cpu": "5m", "memory": "8Mi"},
                            "limits": {"cpu": "50m", "memory": "32Mi"},
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
        subprocess.run(
            k + ["create", "-f", "-"],
            input=json.dumps({"apiVersion": "v1", "kind": "List", "items": [ns, pod]}),
            text=True,
            check=True,
        )
        print(
            call("-n", NS, "wait", "pod/dns", "--for=condition=Ready", "--timeout=180s")
        )
        return
    ns = json.loads(call("get", "namespace", NS, "-o", "json"))
    assert ns["metadata"]["labels"].get("main-control-plane-probe") == "true"
    if args.action == "cleanup":
        print(call("delete", "namespace", NS, "--wait=false"))
        return
    assert args.output
    result = {
        "completed": datetime.now(timezone.utc).isoformat(),
        "api": call("get", "--raw=/readyz"),
        "dns": {},
    }
    result["etcd"] = subprocess.check_output(
        [
            str(base / "talosctl"),
            "--talosconfig",
            str(base / "talosconfig"),
            "-e",
            "10.0.0.221",
            "-n",
            "10.0.0.221",
            "etcd",
            "status",
        ],
        text=True,
    )
    for host in ["kubernetes.default.svc.cluster.local", "example.com"]:
        result["dns"][host] = call("-n", NS, "exec", "dns", "--", "nslookup", host)
    assert result["api"].strip() == "ok"
    result["passed"] = True
    args.output.write_text(json.dumps(result, indent=2))
    print("Laptop API, etcd and internal/external cluster DNS checks passed")


if __name__ == "__main__":
    main()
