import json
import subprocess
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[4]


def test_activation_requires_capacity_and_immutable_images():
    result = subprocess.run(
        [
            "helm",
            "template",
            "test",
            str(ROOT / "charts/homelab-inference"),
            "--set",
            "enabled=true",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Pin the built gateway" in result.stderr


def test_worker_stage_remains_quarantined_and_has_no_gateway():
    output = subprocess.check_output(
        [
            "helm",
            "template",
            "test",
            str(ROOT / "charts/homelab-inference"),
            "--set",
            "workerEnabled=true",
            "--set",
            "devicePluginDigest=sha256:" + "a" * 64,
        ]
    )
    docs = [d for d in yaml.safe_load_all(output) if d]
    assert not any(d["kind"] == "Deployment" for d in docs)
    queue = next(d for d in docs if d["kind"] == "ClusterQueue")
    assert queue["spec"]["queueingStrategy"] == "BestEffortFIFO"
    assert all(
        r["nominalQuota"] in {"0", "0Gi"}
        for r in queue["spec"]["resourceGroups"][0]["flavors"][0]["resources"]
    )


def test_gateway_shared_quota_and_scoped_rbac(tmp_path):
    values = {
        "enabled": True,
        "image": "test@sha256:" + "c" * 64,
        "devicePluginDigest": "sha256:" + "a" * 64,
        "measured": {"cpu": 20, "memoryGi": 30, "scratchGi": 40, "gpu": 1},
        "config": {
            "profiles": [
                {
                    "id": "gpu",
                    "node": "ubuntu-gpu-01",
                    "image": "test@sha256:" + "b" * 64,
                    "acceptedNodeUID": "accepted",
                }
            ]
        },
    }
    path = tmp_path / "values.json"
    path.write_text(json.dumps(values))
    docs = [
        d
        for d in yaml.safe_load_all(
            subprocess.check_output(
                [
                    "helm",
                    "template",
                    "test",
                    str(ROOT / "charts/homelab-inference"),
                    "-f",
                    str(path),
                ]
            )
        )
        if d
    ]
    queue = next(d for d in docs if d["kind"] == "ClusterQueue")
    groups = queue["spec"]["resourceGroups"]
    assert len(groups) == 1
    quotas = {
        r["name"]: r["nominalQuota"] for r in groups[0]["flavors"][0]["resources"]
    }
    assert quotas == {
        "cpu": "12",
        "memory": "24Gi",
        "ephemeral-storage": "40Gi",
        "nvidia.com/gpu": "1",
    }
    gateway = next(d for d in docs if d["kind"] == "Deployment")
    assert gateway["spec"]["replicas"] == 1
    assert gateway["spec"]["strategy"]["type"] == "Recreate"
    assert gateway["spec"]["template"]["spec"]["nodeSelector"] == {
        "kubernetes.io/hostname": "talos-cp-01"
    }
    role = next(d for d in docs if d["kind"] == "ClusterRole")
    assert role["rules"][-1]["resourceNames"] == ["ubuntu-gpu-01"]
    assert role["rules"][-1]["verbs"] == ["patch"]
