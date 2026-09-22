#!/usr/bin/env python3
"""Explicit manual primary-platform stop/restore using a private maintenance snapshot.
Never powers a host, changes claims, stops active Jobs, or changes dormant AI specs.
"""

import argparse
import json
import subprocess
from pathlib import Path

ALLOWED = {
    "arc-systems": {"arc-gha-rs-controller"},
    "cnpg-system": {"cnpg"},
    "homelab-cache": {"nexus", "nexus-postgres"},
    "homelab-jobs": {"argo-workflows-server", "argo-workflows-workflow-controller"},
    "homelab-platform": {"ai-lifecycle", "guest-capacity", "physical-capacity"},
    "homelab-services": {"pihole"},
    "kueue-system": {"kueue-controller-manager"},
    "local-path-storage": {"local-path-provisioner"},
    "tailscale": {"operator"},
    "monitoring": {"prometheus", "loki", "grafana", "alloy", "alertmanager"},
    "argocd": {
        "argocd-server",
        "argocd-repo-server",
        "argocd-redis",
        "argocd-applicationset-controller",
        "argocd-dex-server",
        "argocd-notifications-controller",
    },
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["stop", "restore"])
    parser.add_argument("--journal", required=True, type=Path)
    args = parser.parse_args()
    b = Path.home() / ".local/share/main-control-plane/private"
    k = [
        str(b / "kubectl"),
        "--kubeconfig",
        str(b / "kubeconfig"),
        "--request-timeout=30s",
    ]

    def call(*cmd):
        return subprocess.check_output(k + list(cmd), text=True)

    desired = json.loads((args.journal / "desired.json").read_text())
    intent = json.loads((args.journal / "intent.json").read_text())
    assert intent["host"] == "primary"
    records = []
    for kind in ["deployments", "statefulsets"]:
        for obj in desired[kind]:
            ns, name = obj["metadata"]["namespace"], obj["metadata"]["name"]
            if (kind == "deployments" and name in ALLOWED.get(ns, set())) or (
                kind == "statefulsets"
                and (
                    ns == "tailscale"
                    or (ns == "argocd" and name == "argocd-application-controller")
                )
            ):
                records.append((kind, ns, name, obj))

    def scale(record, replicas):
        kind, ns, name, before = record
        live = json.loads(call("-n", ns, "get", kind, name, "-o", "json"))
        assert live["metadata"]["uid"] == before["metadata"]["uid"]
        current = live["spec"].get("replicas", 1)
        assert current in [0, before["spec"].get("replicas", 1)], (
            f"Concurrent replica change: {ns}/{name}"
        )
        if current != replicas:
            patch = [
                {
                    "op": "test",
                    "path": "/metadata/uid",
                    "value": before["metadata"]["uid"],
                },
                {"op": "test", "path": "/spec/replicas", "value": current},
                {"op": "replace", "path": "/spec/replicas", "value": replicas},
            ]
            print(
                call(
                    "-n",
                    ns,
                    "patch",
                    kind,
                    name,
                    "--type=json",
                    "-p",
                    json.dumps(patch),
                ),
                flush=True,
            )
        if replicas:
            print(
                call(
                    "-n", ns, "rollout", "status", kind + "/" + name, "--timeout=300s"
                ),
                flush=True,
            )
        else:
            selector = live["spec"]["selector"]
            assert not selector.get("matchExpressions")
            labels = ",".join(
                key + "=" + value for key, value in selector["matchLabels"].items()
            )
            print(
                call(
                    "-n",
                    ns,
                    "wait",
                    "pods",
                    "-l",
                    labels,
                    "--for=delete",
                    "--timeout=300s",
                ),
                flush=True,
            )

    cluster = next(
        x
        for x in desired["clusters.postgresql.cnpg.io"]
        if x["metadata"]["namespace"] == "homelab-data"
        and x["metadata"]["name"] == "apps-db"
    )

    def hibernate(stopping):
        live = json.loads(
            call("-n", "homelab-data", "get", "cluster", "apps-db", "-o", "json")
        )
        assert live["metadata"]["uid"] == cluster["metadata"]["uid"]
        old = cluster["metadata"].get("annotations", {}).get("cnpg.io/hibernation")
        current = live["metadata"].get("annotations", {}).get("cnpg.io/hibernation")
        assert current in [old, "on"]
        value = "on" if stopping else old
        annotation = (
            "cnpg.io/hibernation=" + value
            if value is not None
            else "cnpg.io/hibernation-"
        )
        print(
            call(
                "-n",
                "homelab-data",
                "annotate",
                "cluster",
                "apps-db",
                "--overwrite",
                annotation,
            ),
            flush=True,
        )
        condition = "cnpg.io/hibernation=True" if stopping else "Ready=True"
        print(
            call(
                "-n",
                "homelab-data",
                "wait",
                "cluster/apps-db",
                "--for=condition=" + condition,
                "--timeout=300s",
            ),
            flush=True,
        )
        if stopping:
            print(
                call(
                    "-n",
                    "homelab-data",
                    "wait",
                    "pods",
                    "-l",
                    "cnpg.io/cluster=apps-db",
                    "--for=delete",
                    "--timeout=300s",
                ),
                flush=True,
            )

    if args.action == "stop":
        subprocess.run(
            [
                "python3",
                str(Path(__file__).with_name("maintenance.py")),
                "check",
                "--host",
                "primary",
                "--journal",
                str(args.journal),
                "--kubeconfig",
                str(b / "kubeconfig"),
            ],
            check=True,
        )
        done = set()

        def stop_where(predicate):
            for r in records:
                key = r[:3]
                if key not in done and predicate(r):
                    scale(r, 0)
                    done.add(key)

        stop_where(
            lambda r: r[2] in {"ai-lifecycle", "argo-workflows-server", "operator"}
        )
        stop_where(lambda r: r[1] == "tailscale")
        stop_where(lambda r: r[2] in {"pihole", "nexus"})
        stop_where(lambda r: r[2] == "nexus-postgres")
        hibernate(True)
        stop_where(lambda r: r[1] not in {"monitoring", "argocd"})
        print(
            call(
                "-n",
                "arc-systems",
                "delete",
                "pod",
                "-l",
                "app.kubernetes.io/component=runner-scale-set-listener",
                "--wait=true",
                "--timeout=180s",
            ),
            flush=True,
        )
        stop_where(lambda r: r[1] == "argocd")
        for name in ["alloy", "grafana", "prometheus", "loki", "alertmanager"]:
            stop_where(lambda r, n=name: r[1] == "monitoring" and r[2] == n)
        assert len(done) == len(records)
        intent["phase"] = "platform-stopped"
    else:
        volume_before = json.loads((args.journal / "volume-before.json").read_text())
        talos = [
            str(b / "talosctl"),
            "--talosconfig",
            str(b / "talosconfig"),
            "-e",
            "10.0.0.222",
            "-n",
            "10.0.0.222",
        ]
        volume_after = json.loads(
            subprocess.check_output(
                talos
                + ["get", "volumestatus", "u-local-path-provisioner", "-o", "json"]
            )
        )
        for field in [
            "uuid",
            "partitionUUID",
            "location",
            "filesystem",
            "size",
            "phase",
        ]:
            assert volume_before["spec"][field] == volume_after["spec"][field], field
        mounted = json.loads(
            subprocess.check_output(
                talos + ["get", "mountstatus", "u-local-path-provisioner", "-o", "json"]
            )
        )
        assert mounted["spec"]["target"] == "/var/mnt/local-path-provisioner"
        node = json.loads(call("get", "node", "talos-worker-01", "-o", "json"))
        assert not node["spec"].get("unschedulable", False), (
            "Verify storage and restore original schedulability before restoring controllers"
        )
        done = set()

        def restore_where(predicate):
            for r in records:
                key = r[:3]
                if key not in done and predicate(r):
                    scale(r, r[3]["spec"].get("replicas", 1))
                    done.add(key)

        restore_where(
            lambda r: (
                r[2] in {"local-path-provisioner", "kueue-controller-manager", "cnpg"}
            )
        )
        hibernate(False)
        for name in ["nexus-postgres", "nexus", "pihole"]:
            restore_where(lambda r, n=name: r[2] == n)
        restore_where(lambda r: r[1] == "monitoring")
        restore_where(lambda r: r[1] == "argocd")
        restore_where(lambda r: r[1] == "tailscale" and r[0] == "statefulsets")
        restore_where(lambda r: True)
        intent["phase"] = "platform-restored-submissions-paused"
    (args.journal / "intent.json").write_text(json.dumps(intent, indent=2))
    print(intent["phase"])


if __name__ == "__main__":
    main()
