#!/usr/bin/env python3
"""Independent laptop maintenance journal and fail-closed shutdown checks.
This tool never powers hosts off, drains nodes, or cancels active work.
"""

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

LOCAL_KUBECTL = Path.home() / ".local/share/main-control-plane/private/kubectl"
KUBECTL = str(LOCAL_KUBECTL) if LOCAL_KUBECTL.exists() else "kubectl"

KINDS = [
    "deployments",
    "statefulsets",
    "cronjobs",
    "jobs",
    "pods",
    "cronworkflows.argoproj.io",
    "workflows.argoproj.io",
    "autoscalingrunnersets.actions.github.com",
    "ephemeralrunners.actions.github.com",
    "scheduledbackups.postgresql.cnpg.io",
    "backups.postgresql.cnpg.io",
    "clusters.postgresql.cnpg.io",
    "applications.argoproj.io",
    "nodes",
    "pv",
    "pvc",
]


def blockers(objects):
    found = []
    for kind, items in objects.items():
        for obj in items:
            m = obj["metadata"]
            s = obj.get("status", {})
            spec = obj.get("spec", {})
            ident = f"{kind}/{m.get('namespace', '')}/{m['name']}"
            if kind == "jobs" and s.get("active", 0) > 0:
                found.append(ident)
            if kind == "workflows.argoproj.io" and s.get("phase") not in (
                "Succeeded",
                "Failed",
                "Error",
            ):
                found.append(ident)
            if kind == "backups.postgresql.cnpg.io" and s.get("phase") not in (
                "completed",
                "failed",
            ):
                found.append(ident)
            # An extant ephemeral runner might receive a job between samples.
            if kind == "ephemeralrunners.actions.github.com":
                found.append(ident)
            if kind in (
                "cronjobs",
                "cronworkflows.argoproj.io",
                "scheduledbackups.postgresql.cnpg.io",
            ) and not spec.get("suspend", False):
                found.append(ident + " not suspended")
            if kind == "autoscalingrunnersets.actions.github.com" and (
                spec.get("minRunners") != 0 or spec.get("maxRunners") != 0
            ):
                found.append(ident + " submissions not paused")
            if (
                kind == "applications.argoproj.io"
                and spec.get("syncPolicy", {}).get("automated") is not None
            ):
                found.append(ident + " automatic reconciliation enabled")
    return found


def resource_available(kind, available):
    resource = {"pv": "persistentvolumes", "pvc": "persistentvolumeclaims"}.get(
        kind, kind
    )
    return any(
        name == resource or name.startswith(resource + ".") for name in available
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["snapshot", "check"])
    parser.add_argument("--host", required=True, choices=["primary", "secondary"])
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--journal", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    k = [
        KUBECTL,
        "--kubeconfig",
        args.kubeconfig,
        "--server=https://10.0.0.231:6443",
        "--request-timeout=20s",
    ]
    available = subprocess.check_output(
        k + ["api-resources", "-o", "name"], text=True
    ).splitlines()
    objects = {}
    for kind in KINDS:
        if not resource_available(kind, available):
            continue
        objects[kind] = json.loads(
            subprocess.check_output(k + ["get", kind, "-A", "-o", "json"])
        )["items"]
    if args.action == "snapshot":
        args.journal.mkdir(parents=True, mode=0o700, exist_ok=False)
        (args.journal / "desired.json").write_text(json.dumps(objects, indent=2) + "\n")
        (args.journal / "intent.json").write_text(
            json.dumps(
                {
                    "host": args.host,
                    "phase": "preparing",
                    "started": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
            + "\n"
        )
        if args.host == "primary":
            private = Path.home() / ".local/share/main-control-plane/private"
            volume = subprocess.check_output(
                [
                    str(private / "talosctl"),
                    "--talosconfig",
                    str(private / "talosconfig"),
                    "-e",
                    "10.0.0.222",
                    "-n",
                    "10.0.0.222",
                    "get",
                    "volumestatus",
                    "u-local-path-provisioner",
                    "-o",
                    "json",
                ],
                text=True,
            )
            assert json.loads(volume)["spec"]["phase"] == "ready"
            (args.journal / "volume-before.json").write_text(volume)
        print(
            "Desired state saved before changes. Follow the ordered runbook; leave intent until full recovery."
        )
    else:
        assert (args.journal / "desired.json").is_file(), "Capture desired state first"
        if args.host == "primary":
            assert Path("/var/lib/main-control-plane/source-fenced").is_file(), (
                "Control plane has not relocated"
            )
            receipt = Path.home() / ".local/share/main-control-plane/independence.json"
            assert (
                receipt.exists()
                and json.loads(receipt.read_text()).get("passed") is True
            ), "Independence checks not accepted"
            subprocess.run(
                ["systemctl", "is-active", "--quiet", "main-control-plane.service"],
                check=True,
            )
        pending = blockers(objects)
        if pending:
            raise SystemExit("Refusing shutdown:\n" + "\n".join(pending))
        print(
            "Submission/job gate passed. This does not replace storage, CNPG hibernation, Pod, or Talos shutdown checks."
        )


if __name__ == "__main__":
    main()
