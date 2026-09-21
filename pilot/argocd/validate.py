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
    if obj["kind"] in ["Deployment", "StatefulSet"] and obj["spec"].get("replicas", 1):
        spec = obj["spec"]["template"]["spec"]
        assert spec["nodeSelector"] == {"node-role.kubernetes.io/control-plane": ""}
        for container in spec["containers"]:
            limits += int(container["resources"]["limits"]["memory"].removesuffix("Mi"))
assert limits == 1536, limits
print("Pinned manifests and 1536 MiB management-only budget verified")
