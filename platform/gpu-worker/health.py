#!/usr/bin/env python3
"""Read-only, bounded node acceptance observations. Never removes quarantine."""

import argparse
import json
import subprocess
import datetime
from enroll import CLUSTER_UID


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--node", default="ubuntu-gpu-01")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    command = [args.kubectl, "--kubeconfig", args.kubeconfig, "--request-timeout=15s"]

    def get(*parts):
        return json.loads(
            subprocess.check_output(command + list(parts) + ["-o", "json"], timeout=20)
        )

    if get("get", "namespace", "kube-system")["metadata"]["uid"] != CLUSTER_UID:
        raise SystemExit("Wrong cluster")
    node = get("get", "node", args.node)
    pods = get("get", "pods", "-A", "--field-selector", "spec.nodeName=" + args.node)[
        "items"
    ]

    def ready(obj):
        return any(
            c["type"] == "Ready" and c["status"] == "True"
            for c in obj.get("status", {}).get("conditions", [])
        )

    result = {
        "observedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "node": args.node,
        "nodeUID": node["metadata"]["uid"],
        "bootID": node["status"]["nodeInfo"]["bootID"],
        "versions": node["status"]["nodeInfo"],
        "allocatable": node["status"].get("allocatable", {}),
        "ready": ready(node),
        "cilium": any(
            p["metadata"]["namespace"] == "kube-system"
            and p["metadata"].get("labels", {}).get("k8s-app") == "cilium"
            and ready(p)
            for p in pods
        ),
        "taints": node.get("spec", {}).get("taints", []),
        "acceptanceComplete": False,
    }
    # Readiness cannot prove CUDA, DNS, networking, reboot, or inference correctness.
    with open(args.output, "x") as output:
        json.dump(result, output, indent=2)
    print(
        json.dumps(
            {k: result[k] for k in ["node", "ready", "cilium", "acceptanceComplete"]}
        )
    )


if __name__ == "__main__":
    main()
