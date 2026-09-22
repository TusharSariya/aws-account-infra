#!/usr/bin/env python3
"""Offline invariants plus deterministic-render and vendor-integrity checks."""

import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path

import yaml

LOCAL_KUBECTL = Path.home() / ".local/share/main-control-plane/private/kubectl"
KUBECTL = str(LOCAL_KUBECTL) if LOCAL_KUBECTL.exists() else "kubectl"

ROOT = Path(__file__).resolve().parent


def verify_nonroot(objects):
    for obj in objects:
        if obj["kind"] not in ["Deployment", "StatefulSet"]:
            continue
        pod = obj["spec"]["template"]["spec"]
        for container in pod.get("containers", []) + pod.get("initContainers", []):
            effective = {
                **pod.get("securityContext", {}),
                **container.get("securityContext", {}),
            }
            assert effective.get("runAsNonRoot") is True, (
                obj["metadata"]["name"],
                container["name"],
                "must run non-root",
            )
            assert effective.get("runAsUser") != 0


spec = importlib.util.spec_from_file_location(
    "main_renderer", ROOT / "monitoring/render.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert (
    json.loads((ROOT / "monitoring/resources.json").read_text()) == module.render()
), "Regenerate monitoring resources"
monitoring = yaml.safe_load_all(
    subprocess.check_output([KUBECTL, "kustomize", str(ROOT / "monitoring")], text=True)
)
items = list(monitoring)
for o in items:
    text = json.dumps(o)
    assert not any(
        x in text for x in ["pilot", "prototype", "10.0.2.", "host-telemetry"]
    )
    if o["kind"] == "Deployment":
        pod = o["spec"]["template"]["spec"]
        assert pod["nodeSelector"]["homelab.tfdraw.dev/storage"] == "local-primary"
        assert not pod.get("tolerations")
        assert o["spec"]["replicas"] == 1
        for c in pod["containers"]:
            assert re.search(r"@sha256:[a-f0-9]{64}$", c["image"])
            assert all(
                k in c
                for k in [
                    "resources",
                    "readinessProbe",
                    "livenessProbe",
                    "startupProbe",
                ]
            )
    if o["kind"] == "PersistentVolumeClaim":
        assert o["spec"]["storageClassName"] == "local-primary"
        assert "volumeName" not in o["spec"]
        assert (
            o["spec"]["resources"]["requests"]["storage"]
            == module.SIZES[o["metadata"]["name"]]
        )
    if o["kind"] == "Service":
        assert o["spec"]["type"] == "ClusterIP"
    if o["kind"].endswith("Role"):
        for rule in o["rules"]:
            assert "*" not in json.dumps(rule)
            assert (
                "secrets" not in rule["resources"]
                and "nodes/proxy" not in rule["resources"]
            )
assert sum(v[1] for v in module.BUDGETS.values()) == 1216
assert sum(v[2] for v in module.BUDGETS.values()) == 3584
for name, lock in json.loads((ROOT / "argocd/release.json").read_text())[
    "files"
].items():
    assert (
        hashlib.sha256((ROOT / "argocd/vendor" / name).read_bytes()).hexdigest()
        == lock["sha256"]
    )
    if name != "namespace-install.yaml":
        assert (ROOT / "argocd/crds" / name).read_bytes() == (
            ROOT / "argocd/vendor" / name
        ).read_bytes()
verify_nonroot(
    yaml.safe_load_all((ROOT / "argocd/vendor/namespace-install.yaml").read_text())
)
argocd = list(
    yaml.safe_load_all(
        subprocess.check_output([KUBECTL, "kustomize", str(ROOT / "argocd")], text=True)
    )
)
verify_nonroot(argocd)
for o in argocd:
    assert o["kind"] not in [
        "Application",
        "ClusterRole",
        "ClusterRoleBinding",
        "Ingress",
    ]
    assert "pilot" not in json.dumps(o)
    if o["kind"] == "AppProject":
        assert not o["spec"]["sourceRepos"] and not o["spec"]["destinations"]
    if o["kind"] in ["Deployment", "StatefulSet"] and o["spec"].get("replicas", 1):
        pod = o["spec"]["template"]["spec"]
        assert pod["nodeSelector"] == {"homelab.tfdraw.dev/worker-role": "primary"}
        assert not pod.get("tolerations")
        assert all("resources" in c for c in pod["containers"])
print(
    "Main manifests: placement, storage, RBAC, budgets, isolation and vendor checks passed"
)
