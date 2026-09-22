#!/usr/bin/env python3
"""Restore only submission fields changed by the explicitly recorded maintenance."""

import argparse
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args()
    desired = json.loads((args.journal / "desired.json").read_text())
    b = Path.home() / ".local/share/main-control-plane/private"
    k = [
        str(b / "kubectl"),
        "--kubeconfig",
        str(b / "kubeconfig"),
        "--request-timeout=30s",
    ]
    deployments = json.loads(
        subprocess.check_output(k + ["get", "deployments", "-A", "-o", "json"])
    )["items"]
    assert all(
        d["spec"].get("replicas", 1) == d.get("status", {}).get("availableReplicas", 0)
        for d in deployments
    ), "Restore deployment health before submissions"
    for kind in [
        "cronjobs",
        "cronworkflows.argoproj.io",
        "scheduledbackups.postgresql.cnpg.io",
        "autoscalingrunnersets.actions.github.com",
    ]:
        for old in desired.get(kind, []):
            m = old["metadata"]
            live = json.loads(
                subprocess.check_output(
                    k + ["-n", m["namespace"], "get", kind, m["name"], "-o", "json"]
                )
            )
            assert live["metadata"]["uid"] == m["uid"]
            fields = (
                {"minRunners": 0, "maxRunners": 0}
                if kind.startswith("autoscaling")
                else {"suspend": True}
            )
            patch = [{"op": "test", "path": "/metadata/uid", "value": m["uid"]}]
            for field, paused in fields.items():
                prior = old["spec"].get(field)
                current = live["spec"].get(field)
                if current == prior:
                    continue
                assert current == paused, (
                    f"Concurrent change: {kind}/{m['name']}/{field}"
                )
                patch.append({"op": "test", "path": "/spec/" + field, "value": paused})
                patch.append(
                    {"op": "replace", "path": "/spec/" + field, "value": prior}
                    if field in old["spec"]
                    else {"op": "remove", "path": "/spec/" + field}
                )
            if len(patch) > 1:
                subprocess.run(
                    k
                    + [
                        "-n",
                        m["namespace"],
                        "patch",
                        kind,
                        m["name"],
                        "--type=json",
                        "-p",
                        json.dumps(patch),
                    ],
                    check=True,
                )
    print("Original schedule/runner fields restored; other specs preserved")


if __name__ == "__main__":
    main()
