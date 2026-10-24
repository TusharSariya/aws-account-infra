#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML==6.0.3"]
# ///
"""Reconcile an explicitly disabled desktop before retained-server acceptance."""

import argparse
import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def changes(node, queue, deployment, expected_uid):
    if (
        node["metadata"]["name"] != "ubuntu-gpu-01"
        or node["metadata"]["uid"] != expected_uid
    ):
        raise ValueError("Desktop node identity changed")
    taints = list(node["spec"].get("taints", []))
    compute = {
        "key": "homelab.tfdraw.dev/compute",
        "value": "true",
        "effect": "NoSchedule",
    }
    if compute not in taints:
        raise ValueError("Expected desktop compute isolation")
    quarantine = {
        "key": "homelab.tfdraw.dev/quarantine",
        "value": "true",
        "effect": "NoSchedule",
    }
    if any(t["key"] == quarantine["key"] and t != quarantine for t in taints):
        raise ValueError("Unexpected quarantine configuration")
    if quarantine not in taints:
        taints.append(quarantine)
    groups = queue["spec"]["resourceGroups"]
    if len(groups) != 1 or [f["name"] for f in groups[0]["flavors"]] != [
        "desktop-compute"
    ]:
        raise ValueError("Refusing a shared or changed desktop queue")
    quotas = []
    for index, resource in enumerate(groups[0]["flavors"][0]["resources"]):
        quotas.append(
            {
                "op": "replace",
                "path": f"/spec/resourceGroups/0/flavors/0/resources/{index}/nominalQuota",
                "value": "0",
            }
        )
    result = [
        ("nodes", node, [{"op": "add", "path": "/spec/taints", "value": taints}]),
        (
            "clusterqueues.kueue.x-k8s.io",
            queue,
            quotas + [{"op": "add", "path": "/spec/stopPolicy", "value": "Hold"}],
        ),
    ]
    if deployment:
        if (
            deployment["spec"]["template"]["spec"]["nodeSelector"].get(
                "kubernetes.io/hostname"
            )
            != "ubuntu-gpu-01"
        ):
            raise ValueError("Desktop deployment target changed")
        result.append(
            (
                "deployments",
                deployment,
                [{"op": "replace", "path": "/spec/replicas", "value": 0}],
            )
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--kubectl", required=True)
    args = parser.parse_args()
    config = ROOT / "config/environments/kubernetes/homelab"
    inference = yaml.safe_load((config / "inference-values.yaml").read_text())
    playground = yaml.safe_load((config / "playground-values.yaml").read_text())
    if (
        inference["enabled"]
        or inference["desktopQuota"]
        or playground["desktop"]["enabled"]
    ):
        print("Desktop admission policy is enabled; no disable action requested")
        return
    command = [args.kubectl, "--kubeconfig", args.kubeconfig, "--request-timeout=30s"]

    def run(*words):
        r = subprocess.run(
            command + list(words),
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if r.returncode:
            raise RuntimeError(
                "Desktop policy reconciliation failed; inspect Kubernetes state"
            )
        return json.loads(r.stdout) if r.stdout.strip() else None

    node = run("get", "node", "ubuntu-gpu-01", "-o", "json")
    queue = run("get", "clusterqueue", "desktop-compute", "-o", "json")
    deployment = run(
        "get",
        "deployment",
        "desktop-ollama",
        "-n",
        "homelab-inference",
        "--ignore-not-found",
        "-o",
        "json",
    )
    for kind, obj, patch in changes(
        node, queue, deployment, inference["desktopAcceptedNodeUID"]
    ):
        meta = obj["metadata"]
        guards = [
            {"op": "test", "path": "/metadata/" + key, "value": meta[key]}
            for key in ("uid", "resourceVersion")
        ]
        namespace = ["-n", meta["namespace"]] if meta.get("namespace") else []
        run(
            "patch",
            kind,
            meta["name"],
            *namespace,
            "--type=json",
            "-p",
            json.dumps(guards + patch),
            "-o",
            "json",
        )
    print(
        "Desktop admission disabled and node quarantined; persistent storage retained"
    )


if __name__ == "__main__":
    main()
