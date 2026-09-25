#!/usr/bin/env python3
"""Require networking on awake nodes and preserve optional desktop quarantine."""

import json
import os
import subprocess
import time


def ready(obj):
    return any(
        c.get("type") == "Ready" and c.get("status") == "True"
        for c in obj.get("status", {}).get("conditions", [])
    )


def verify(nodes, pods):
    for node in nodes:
        name = node["metadata"]["name"]
        # This manually powered, explicitly enrolled desktop is outside retained
        # server availability. Quarantine still disables its normal admission.
        # Check its networking whenever awake; never exempt an unknown node or
        # an admission-enabled desktop merely because it is unavailable.
        taints = {
            (t.get("key"), t.get("value"), t.get("effect"))
            for t in node["spec"].get("taints", [])
        }
        quarantined_desktop = (
            name == "ubuntu-gpu-01"
            and not ready(node)
            and {
                ("homelab.tfdraw.dev/quarantine", "true", "NoSchedule"),
                ("homelab.tfdraw.dev/compute", "true", "NoSchedule"),
            } <= taints
        )
        sleeping = (
            name == "talos-worker-02"
            and node["metadata"]
            .get("annotations", {})
            .get("homelab.tfdraw.dev/power-intent")
            == "sleep"
            and node["spec"].get("unschedulable")
            and not ready(node)
        )
        if sleeping or quarantined_desktop:
            continue
        if not ready(node):
            raise ValueError("Unexpected unavailable node: " + name)
        for daemon in ["cilium", "cilium-envoy", "kube-proxy"]:
            matches = [
                p
                for p in pods
                if p["spec"].get("nodeName") == name
                and not p["metadata"].get("deletionTimestamp")
                and any(
                    o.get("kind") == "DaemonSet" and o.get("name") == daemon
                    for o in p["metadata"].get("ownerReferences", [])
                )
            ]
            if len(matches) != 1 or not ready(matches[0]):
                raise ValueError("Networking is not ready: " + name + "/" + daemon)


def main():
    command = [os.environ.get("KUBECTL", "kubectl"), "--request-timeout=30s"]
    deadline = time.monotonic() + 300
    while True:
        nodes = json.loads(
            subprocess.check_output(command + ["get", "nodes", "-o", "json"])
        )["items"]
        pods = json.loads(
            subprocess.check_output(
                command + ["get", "pods", "-n", "kube-system", "-o", "json"]
            )
        )["items"]
        try:
            verify(nodes, pods)
            print("PASS: networking ready on awake nodes")
            return
        except ValueError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(5)


if __name__ == "__main__":
    main()
