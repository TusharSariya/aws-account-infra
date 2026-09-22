#!/usr/bin/env python3
"""Four owned Jobs, 1 CPU total, 512 MiB total, ten minutes. No scaling controller."""

import argparse
import json
import secrets
import subprocess
from pathlib import Path

LOCAL_KUBECTL = Path.home() / ".local/share/main-control-plane/private/kubectl"
KUBECTL = str(LOCAL_KUBECTL) if LOCAL_KUBECTL.exists() else "kubectl"

IMAGE = "docker.io/library/busybox:1.37.0@sha256:9db7b59979c38555a39def84a31fb98b5296952f9e3afd4f6f11f05b07adfab0"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    args.evidence.mkdir(mode=0o700, parents=True, exist_ok=False)
    run = "main-load-" + secrets.token_hex(5)
    k = [
        KUBECTL,
        "--kubeconfig",
        args.kubeconfig,
        "--server=https://10.0.0.231:6443",
        "--request-timeout=30s",
        "-n",
        "monitoring",
    ]
    names = []
    try:
        for index in range(4):
            name = f"{run}-{index}"
            job = {
                "apiVersion": "batch/v1",
                "kind": "Job",
                "metadata": {
                    "name": name,
                    "namespace": "monitoring",
                    "labels": {"main-acceptance": run},
                },
                "spec": {
                    "backoffLimit": 0,
                    "activeDeadlineSeconds": 900,
                    "template": {
                        "metadata": {"labels": {"main-acceptance": run}},
                        "spec": {
                            "restartPolicy": "Never",
                            "automountServiceAccountToken": False,
                            "nodeSelector": {
                                "homelab.tfdraw.dev/worker-role": "primary"
                            },
                            "securityContext": {
                                "runAsNonRoot": True,
                                "runAsUser": 65534,
                                "runAsGroup": 65534,
                                "fsGroup": 65534,
                                "seccompProfile": {"type": "RuntimeDefault"},
                            },
                            "volumes": [
                                {
                                    "name": "scratch",
                                    "emptyDir": {
                                        "medium": "Memory",
                                        "sizeLimit": "48Mi",
                                    },
                                }
                            ],
                            "containers": [
                                {
                                    "name": "load",
                                    "image": IMAGE,
                                    "command": [
                                        "sh",
                                        "-ec",
                                        'dd if=/dev/zero of=/scratch/data bs=1M count=32; end=$(($(date +%s)+600)); while [ "$(date +%s)" -lt "$end" ]; do sha256sum /scratch/data >/dev/null; done',
                                    ],
                                    "volumeMounts": [
                                        {"name": "scratch", "mountPath": "/scratch"}
                                    ],
                                    "securityContext": {
                                        "allowPrivilegeEscalation": False,
                                        "readOnlyRootFilesystem": True,
                                        "capabilities": {"drop": ["ALL"]},
                                    },
                                    "resources": {
                                        "requests": {"cpu": "250m", "memory": "128Mi"},
                                        "limits": {"cpu": "250m", "memory": "128Mi"},
                                    },
                                }
                            ],
                        },
                    },
                },
            }
            subprocess.run(
                k + ["create", "-f", "-"], input=json.dumps(job), text=True, check=True
            )
            names.append(name)
        subprocess.run(
            k
            + [
                "wait",
                "pods",
                "-l",
                "main-acceptance=" + run,
                "--for=condition=Ready",
                "--timeout=180s",
            ],
            check=True,
        )
        subprocess.run(
            [
                "python3",
                str(Path.home() / "main-control-plane/capacity.py"),
                "--seconds",
                "600",
                "--output",
                str(args.evidence / "capacity.json"),
            ],
            check=True,
        )
        subprocess.run(
            k
            + [
                "wait",
                "jobs",
                "-l",
                "main-acceptance=" + run,
                "--for=condition=Complete",
                "--timeout=300s",
            ],
            check=True,
        )
        for kind in ["jobs", "pods"]:
            data = subprocess.check_output(
                k + ["get", kind, "-l", "main-acceptance=" + run, "-o", "json"],
                text=True,
            )
            (args.evidence / (kind + ".json")).write_text(data)
        print("Four bounded Jobs and capacity gate passed")
    finally:
        for name in names:
            subprocess.run(
                k + ["delete", "job", name, "--ignore-not-found", "--wait=true"],
                check=False,
            )


if __name__ == "__main__":
    main()
