"""Validate security/storage invariants locally and native configs on the pilot host."""

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import BASE, run
from render import ROOT, NS, NODE, SIZES, render


def validate():
    objects = render()
    on_disk = json.loads((ROOT / "resources.json").read_text())["items"]
    if objects != on_disk:
        raise RuntimeError("Generated manifests are stale; run render.py")
    for obj in objects:
        kind = obj["kind"]
        if kind == "Deployment":
            spec = obj["spec"]["template"]["spec"]
            assert obj["spec"]["replicas"] == 1
            assert spec["nodeSelector"]["kubernetes.io/hostname"] == NODE
            assert spec["securityContext"]["runAsNonRoot"]
            assert spec["tolerations"]
            for c in spec["containers"]:
                assert "@sha256:" in c["image"]
                assert all(
                    key in c
                    for key in ["readinessProbe", "livenessProbe", "startupProbe"]
                )
                assert c["securityContext"]["capabilities"]["drop"] == ["ALL"]
                assert not c["securityContext"]["allowPrivilegeEscalation"]
        elif kind == "Service":
            assert obj["spec"]["type"] == "ClusterIP"
        elif kind == "PersistentVolume":
            assert obj["spec"]["persistentVolumeReclaimPolicy"] == "Retain"
            assert obj["spec"]["local"]["path"].startswith("/var/mnt/pilot-")
            assert obj["spec"]["claimRef"]["namespace"] == NS
        elif kind in ["Role", "ClusterRole"]:
            assert all(
                set(rule["verbs"]) <= {"get", "list", "watch"} for rule in obj["rules"]
            )
            assert not any(
                "secrets" in rule["resources"] or "*" in rule["resources"]
                for rule in obj["rules"]
            )
    volumes = (ROOT.parents[1] / "vm/user-volumes.yaml").read_text()
    assert volumes.count("kind: UserVolumeConfig") == len(SIZES)
    assert volumes.count("disk.serial == 'PILOT-MONITORING-01'") == len(SIZES)
    print("Manifest identity, storage, image and security invariants passed")


def native():
    # Only temporary public/synthetic paths are substituted. Production config stays untouched.
    configs = {
        o["metadata"]["name"]: o["data"] for o in render() if o["kind"] == "ConfigMap"
    }
    with tempfile.TemporaryDirectory(prefix="pilot-validate-") as directory:
        tmp = Path(directory)
        for name, values in configs.items():
            target = tmp / name
            target.mkdir()
            for filename, content in values.items():
                content = (
                    content.replace("/etc/pilot/", str(target) + "/")
                    .replace("/etc/host/", str(tmp / "host") + "/")
                    .replace(
                        "/var/run/secrets/kubernetes.io/serviceaccount/",
                        str(tmp / "host") + "/",
                    )
                    .replace("/etc/proofs/", str(tmp / "proofs") + "/")
                    .replace("/data", str(tmp / "data"))
                )
                (target / filename).write_text(content)
        (tmp / "host").mkdir()
        (tmp / "host/ca.crt").write_bytes((BASE / "private/ca.crt").read_bytes())
        (tmp / "host/token").write_text("validation-only")
        (tmp / "proofs").mkdir()
        (tmp / "data").mkdir()
        (tmp / "prometheus/alert-tests.yml").write_bytes(
            (ROOT.parent / "config/alert-tests.yml").read_bytes()
        )
        release = BASE / "releases"
        for pattern, args in [
            (
                "**/promtool",
                ["check", "config", str(tmp / "prometheus/prometheus.yml")],
            ),
            ("**/promtool", ["check", "rules", str(tmp / "prometheus/alerts.yml")]),
            (
                "**/loki-linux-amd64",
                ["-config.file=" + str(tmp / "loki/loki.yml"), "-verify-config=true"],
            ),
            ("**/alloy-linux-amd64", ["validate", str(tmp / "alloy/alloy.alloy")]),
            ("**/amtool", ["check-config", str(tmp / "alertmanager/alertmanager.yml")]),
        ]:
            matches = [p for p in release.glob(pattern) if p.is_file()]
            if len(matches) != 1:
                raise RuntimeError("Expected exactly one pinned binary for " + pattern)
            print(run([str(matches[0]), *args], timeout=60))
        promtool = next(release.glob("**/promtool"))
        print(
            run(
                [str(promtool), "test", "rules", "alert-tests.yml"],
                cwd=tmp / "prometheus",
                timeout=60,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    validate()
    if args.native:
        native()
