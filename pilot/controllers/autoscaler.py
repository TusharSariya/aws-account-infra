"""Bound provisioning retry latency for this small, fixed-capacity pilot."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "monitoring"))
from common import BASE, get, identity, kubectl

NAME = "prototype-slot-ca"
NAMESPACE = "prototype-slot"
IMAGE = "registry.k8s.io/autoscaling/cluster-autoscaler:v1.36.1@sha256:461388d03eb5b55db58941ee7a81d9a619dd15302b01cbab9f5a9946715994b4"
FLAGS = {
    "--provisioning-request-initial-backoff-time": "2s",
    "--provisioning-request-max-backoff-time": "5s",
}


def tuned(args):
    if any(sum(a.startswith(key + "=") for a in args) != 1 for key in FLAGS):
        raise RuntimeError("Expected exactly one existing value for each backoff flag")
    result = [
        a.split("=", 1)[0] + "=" + FLAGS[a.split("=", 1)[0]]
        if a.split("=", 1)[0] in FLAGS
        else a
        for a in args
    ]
    scans = [a for a in args if a.startswith("--scan-interval=")]
    if len(scans) > 1:
        raise RuntimeError("Duplicate scan interval")
    result = [a for a in result if not a.startswith("--scan-interval=")]
    return [*result, "--scan-interval=2s"]


def main(action):
    identity(admin=True)
    deployment = get("deployment", NAME, "-n", NAMESPACE, admin=True)
    containers = deployment["spec"]["template"]["spec"]["containers"]
    if len(containers) != 1 or containers[0]["image"] != IMAGE:
        raise RuntimeError("Unexpected autoscaler image or container layout")
    current = containers[0]["args"]
    checkpoint = BASE / "migration/autoscaler-args.json"
    if action == "tune":
        desired = tuned(current)
        if not checkpoint.exists():
            checkpoint.write_text(json.dumps(current))
    else:
        desired = json.loads(checkpoint.read_text())
    if current != desired:
        kubectl(
            "patch",
            "deployment",
            NAME,
            "-n",
            NAMESPACE,
            "--type=json",
            "-p",
            json.dumps(
                [
                    {
                        "op": "test",
                        "path": "/spec/template/spec/containers/0/args",
                        "value": current,
                    },
                    {
                        "op": "replace",
                        "path": "/spec/template/spec/containers/0/args",
                        "value": desired,
                    },
                ]
            ),
            admin=True,
        )
    kubectl(
        "rollout",
        "status",
        "deployment/" + NAME,
        "-n",
        NAMESPACE,
        "--timeout=180s",
        admin=True,
        timeout=200,
    )
    print("Autoscaler retry configuration: " + action)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["tune", "restore"])
    main(parser.parse_args().action)
