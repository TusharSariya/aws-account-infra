#!/usr/bin/env python3
"""Durable CI maintenance holds, reachable through the always-on Kubernetes API."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import uuid


def restored(nodes, nexus):
    return (
        all(
            not n["spec"].get("unschedulable")
            and not any(
                k in n["metadata"].get("annotations", {})
                for k in (
                    "homelab.tfdraw.dev/power-operation",
                    "homelab.tfdraw.dev/power-intent",
                )
            )
            and any(
                c["type"] == "Ready" and c["status"] == "True"
                for c in n["status"]["conditions"]
            )
            for n in nodes
        )
        and nexus.get("status", {}).get("availableReplicas", 0) > 0
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["acquire", "release"])
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--hosts", choices=["primary", "primary,secondary"], default="primary"
    )
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    command = ["kubectl", "--kubeconfig", args.kubeconfig, "--request-timeout=20s"]

    def run(*argv, body=None):
        result = subprocess.run(
            command + list(argv), input=body, text=True, capture_output=True, timeout=30
        )
        if result.returncode:
            raise RuntimeError(
                "Hold operation failed; inspect Kubernetes hold before retrying"
            )
        return json.loads(result.stdout) if result.stdout.strip() else None

    if args.action == "acquire":
        if args.receipt.exists():
            raise ValueError("Existing hold receipt requires explicit release")
        name = "host-hold-" + str(uuid.uuid4())
        manifest = {
            "apiVersion": "coordination.k8s.io/v1",
            "kind": "Lease",
            "metadata": {
                "name": name,
                "namespace": "homelab-platform",
                "labels": {"homelab.tfdraw.dev/power-hold": "true"},
                "annotations": {"homelab.tfdraw.dev/hosts": args.hosts},
            },
            "spec": {
                "holderIdentity": "github-" + os.environ.get("GITHUB_RUN_ID", "local")
            },
        }
        # Record the unique intent before submitting it; interrupted creates can
        # be inspected and released using this receipt without guessing a name.
        args.receipt.write_text(json.dumps({"name": name, "hosts": args.hosts}))
        result = run("create", "-f", "-", "-o", "json", body=json.dumps(manifest))
        args.receipt.write_text(
            json.dumps(
                {"name": name, "uid": result["metadata"]["uid"], "hosts": args.hosts}
            )
        )
        if args.wait:
            deadline = time.monotonic() + 1200
            while time.monotonic() < deadline:
                names = ["talos-worker-01"] + (
                    ["talos-worker-02"] if "secondary" in args.hosts else []
                )
                nodes = [run("get", "node", n, "-o", "json") for n in names]
                nexus = run(
                    "get", "deployment", "nexus", "-n", "homelab-cache", "-o", "json"
                )
                if restored(nodes, nexus):
                    break
                time.sleep(10)
            else:
                raise RuntimeError(
                    "Wake deadline exceeded; hold remains until released"
                )
        print("Maintenance hold acquired: " + name)
    else:
        receipt = json.loads(args.receipt.read_text())
        lease = run(
            "get", "lease", receipt["name"], "-n", "homelab-platform", "-o", "json"
        )
        if lease["metadata"]["uid"] != receipt.get("uid"):
            raise ValueError("Hold identity is uncertain; inspect before release")
        patch = [
            {"op": "test", "path": "/metadata/uid", "value": receipt["uid"]},
            {
                "op": "test",
                "path": "/metadata/resourceVersion",
                "value": lease["metadata"]["resourceVersion"],
            },
            {
                "op": "replace",
                "path": "/metadata/labels/homelab.tfdraw.dev~1power-hold",
                "value": "false",
            },
        ]
        run(
            "patch",
            "lease",
            receipt["name"],
            "-n",
            "homelab-platform",
            "--type=json",
            "-p",
            json.dumps(patch),
            "-o",
            "json",
        )
        # Released receipts/Leases remain as non-secret audit evidence.
        print("Maintenance hold released: " + receipt["name"])


if __name__ == "__main__":
    main()
