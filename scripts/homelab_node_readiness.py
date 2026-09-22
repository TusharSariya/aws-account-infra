#!/usr/bin/env python3
"""Require networking on awake nodes; exclude only explicitly sleeping workers."""

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
        sleeping = (
            name == "talos-worker-02"
            and node["metadata"]
            .get("annotations", {})
            .get("homelab.tfdraw.dev/power-intent")
            == "sleep"
            and node["spec"].get("unschedulable")
            and not ready(node)
        )
        if sleeping:
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
