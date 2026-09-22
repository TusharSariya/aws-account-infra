#!/usr/bin/env python3
"""Add a distinct start-only lifecycle credential; preserve all existing secrets."""

import argparse
import base64
import json
import secrets
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kubeconfig", required=True)
    args = p.parse_args()
    k = ["kubectl", "--kubeconfig", args.kubeconfig, "--request-timeout=30s"]

    def run(*cmd, data=None):
        return subprocess.check_output(k + list(cmd), input=data, timeout=40)

    source = json.loads(
        run(
            "-n",
            "homelab-platform",
            "get",
            "secret",
            "ai-lifecycle-credentials",
            "-o",
            "json",
        )
    )
    if "gateway" not in source["data"]:
        token = base64.b64encode(secrets.token_urlsafe(32).encode()).decode()
        patch = [
            {"op": "test", "path": "/metadata/uid", "value": source["metadata"]["uid"]},
            {
                "op": "test",
                "path": "/metadata/resourceVersion",
                "value": source["metadata"]["resourceVersion"],
            },
            {"op": "add", "path": "/data/gateway", "value": token},
        ]
        # Send private patch through stdin, never process argv or command output.
        run(
            "-n",
            "homelab-platform",
            "patch",
            "secret",
            "ai-lifecycle-credentials",
            "--type=json",
            "--patch-file=/dev/stdin",
            data=json.dumps(patch).encode(),
        )
    else:
        token = source["data"]["gateway"]
    existing = run(
        "-n",
        "homelab-models",
        "get",
        "secret",
        "wake-lifecycle-auth",
        "--ignore-not-found",
        "-o",
        "json",
    )
    if existing.strip():
        if json.loads(existing)["data"] != {"token": token}:
            raise ValueError(
                "Existing gateway credential differs; refusing implicit rotation"
            )
    else:
        obj = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "wake-lifecycle-auth", "namespace": "homelab-models"},
            "type": "Opaque",
            "data": {"token": token},
        }
        run("create", "-f", "-", data=json.dumps(obj).encode())
    print("Start-only gateway credential enrolled; existing credentials preserved")


if __name__ == "__main__":
    main()
