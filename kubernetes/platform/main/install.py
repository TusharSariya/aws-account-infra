#!/usr/bin/env python3
"""Stage monitoring, then gated Argo CD. Does not onboard Git repositories."""

import argparse
import json
import secrets
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

LOCAL_KUBECTL = Path.home() / ".local/share/main-control-plane/private/kubectl"
KUBECTL = str(LOCAL_KUBECTL) if LOCAL_KUBECTL.exists() else "kubectl"

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("component", choices=["monitoring", "argocd"])
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--acceptance", required=True, type=Path)
    args = parser.parse_args()
    gate = json.loads(args.acceptance.read_text())
    expected = "control-plane" if args.component == "monitoring" else "monitoring"
    assert gate.get("component") == expected and gate.get("passed") is True, (
        f"{expected} acceptance required"
    )
    assert (
        datetime.now(timezone.utc) - datetime.fromisoformat(gate["completed"])
    ).total_seconds() < 86400, "Acceptance older than 24h"
    k = [
        KUBECTL,
        "--kubeconfig",
        args.kubeconfig,
        "--server=https://10.0.0.231:6443",
        "--request-timeout=30s",
    ]
    subprocess.run(["python3", str(ROOT / "validate.py")], check=True)
    if args.component == "monitoring":
        # Preserve every existing class, claim and binding.
        subprocess.run(
            k + ["apply", "-f", str(ROOT / "placement/storage-class.yaml")], check=True
        )
        subprocess.run(
            k + ["create", "namespace", "monitoring", "--dry-run=client", "-o", "json"],
            check=True,
            capture_output=True,
        )
        ns = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": "monitoring",
                "labels": {"pod-security.kubernetes.io/enforce": "restricted"},
            },
        }
        subprocess.run(
            k + ["apply", "-f", "-"], input=json.dumps(ns), text=True, check=True
        )
        existing = subprocess.run(
            k
            + [
                "-n",
                "monitoring",
                "get",
                "secret",
                "grafana-admin",
                "--ignore-not-found",
                "-o",
                "name",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        if not existing.stdout.strip():
            secret = {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "grafana-admin", "namespace": "monitoring"},
                "stringData": {"password": secrets.token_urlsafe(32)},
            }
            subprocess.run(
                k + ["create", "-f", "-"],
                input=json.dumps(secret),
                text=True,
                check=True,
                capture_output=True,
            )
    else:
        subprocess.run(
            k
            + [
                "apply",
                "--server-side",
                "--field-manager=main-platform",
                "-k",
                str(ROOT / "argocd/crds"),
            ],
            check=True,
        )
        for name in ["applications", "applicationsets", "appprojects"]:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                crd = json.loads(
                    subprocess.check_output(
                        k + ["get", f"crd/{name}.argoproj.io", "-o", "json"]
                    )
                )
                if any(
                    c["type"] == "Established" and c["status"] == "True"
                    for c in crd.get("status", {}).get("conditions", [])
                ):
                    break
                time.sleep(2)
            else:
                raise SystemExit(f"CRD {name} did not become Established")
    if args.component == "argocd":
        subprocess.run(
            k + ["apply", "-f", str(ROOT / "argocd/namespace.yaml")], check=True
        )
        existing = subprocess.check_output(
            k
            + [
                "-n",
                "argocd",
                "get",
                "secret",
                "argocd-redis",
                "--ignore-not-found",
                "-o",
                "name",
            ],
            text=True,
        )
        if not existing.strip():
            secret = {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "argocd-redis", "namespace": "argocd"},
                "stringData": {"auth": secrets.token_urlsafe(32)},
            }
            subprocess.run(
                k + ["create", "-f", "-"],
                input=json.dumps(secret),
                text=True,
                capture_output=True,
                check=True,
            )
    subprocess.run(k + ["apply", "-k", str(ROOT / args.component)], check=True)
    subprocess.run(
        k
        + [
            "-n",
            args.component if args.component == "monitoring" else "argocd",
            "rollout",
            "status",
            "deployment",
            "--timeout=300s",
        ],
        check=True,
    )
    if args.component == "argocd":
        subprocess.run(
            k
            + [
                "-n",
                "argocd",
                "rollout",
                "status",
                "statefulset/argocd-application-controller",
                "--timeout=300s",
            ],
            check=True,
        )
    print("Installed; live acceptance is still required")


if __name__ == "__main__":
    main()
