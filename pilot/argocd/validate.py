"""Offline validation of pinned vendor content and management-only placement."""

import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
for filename, lock in json.loads((ROOT / "release.json").read_text())["files"].items():
    assert (
        hashlib.sha256((ROOT / "vendor" / filename).read_bytes()).hexdigest()
        == lock["sha256"]
    )
limits = 0
for obj in yaml.safe_load_all(Path(sys.argv[1]).read_text()):
    assert obj["kind"] not in ["ClusterRole", "ClusterRoleBinding"]
    if obj["kind"] in ["Deployment", "StatefulSet"]:
        pod = obj["spec"]["template"]["spec"]
        for container in pod["containers"] + pod.get("initContainers", []):
            security = {
                **pod.get("securityContext", {}),
                **container.get("securityContext", {}),
            }
            assert security.get("runAsNonRoot") is True, container["name"]
            assert security.get("runAsUser", 1) != 0, container["name"]
    if obj["kind"] in ["Deployment", "StatefulSet"] and obj["spec"].get("replicas", 1):
        spec = obj["spec"]["template"]["spec"]
        assert spec["nodeSelector"] == {"node-role.kubernetes.io/control-plane": ""}
        for container in spec["containers"]:
            limits += int(container["resources"]["limits"]["memory"].removesuffix("Mi"))
assert limits == 1536, limits
print("Pinned manifests and 1536 MiB management-only budget verified")

roles = [
    o
    for o in yaml.safe_load_all((ROOT / "access.yaml").read_text())
    if o["kind"] == "Role"
]
assert len(roles) == 1
assert roles[0]["metadata"] == {"name": "pilot-argocd", "namespace": "pilot-app"}
assert roles[0]["rules"] == [
    {
        "apiGroups": ["apps"],
        "resources": ["deployments", "replicasets"],
        "verbs": ["get", "list", "watch", "create", "patch", "update", "delete"],
    },
    {
        "apiGroups": [""],
        "resources": ["services"],
        "verbs": ["get", "list", "watch", "create", "patch", "update", "delete"],
    },
    {
        "apiGroups": [""],
        "resources": ["pods", "events"],
        "verbs": ["get", "list", "watch"],
    },
]
print("Effective non-root security and namespace-only service management verified")
