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


def test_additional_desktop_has_matching_flavor_plugin_and_patch_scope(tmp_path):
    values = {
        "workerEnabled": True,
        "enabled": True,
        "image": "test@sha256:" + "c" * 64,
        "devicePluginDigest": "sha256:" + "a" * 64,
        "measured": {"cpu": 12, "memoryGi": 24, "scratchGi": 40, "gpu": 1},
        "additionalDesktops": [
            {
                "name": "desktop-two",
                "node": "ubuntu-gpu-02",
                "measured": {"cpu": 8, "memoryGi": 16, "scratchGi": 30, "gpu": 1},
            }
        ],
        "config": {
            "profiles": [
                {
                    "id": "gpu2",
                    "node": "ubuntu-gpu-02",
                    "desktop": True,
                    "queue": "desktop",
                    "enabled": True,
                    "acceptedNodeUID": "uid2",
                    "image": "test@sha256:" + "b" * 64,
                }
            ]
        },
    }
    path = tmp_path / "values.json"
    path.write_text(json.dumps(values))
    output = subprocess.check_output(
        [
            "helm",
            "template",
            "test",
            str(ROOT / "charts/homelab-inference"),
            "-f",
            str(path),
        ]
    )
    docs = [d for d in yaml.safe_load_all(output) if d]
    flavors = {
        d["metadata"]["name"]: d["spec"]["nodeLabels"]
        for d in docs
        if d["kind"] == "ResourceFlavor"
    }
    assert flavors["desktop-two"] == {"kubernetes.io/hostname": "ubuntu-gpu-02"}
    queue = next(d for d in docs if d["kind"] == "ClusterQueue")
    assert [f["name"] for f in queue["spec"]["resourceGroups"][0]["flavors"]] == [
        "desktop-compute",
        "desktop-two",
    ]
    role = next(d for d in docs if d["kind"] == "ClusterRole")
    assert role["rules"][-1]["resourceNames"] == ["ubuntu-gpu-01", "ubuntu-gpu-02"]
    plugin = next(d for d in docs if d["kind"] == "DaemonSet")
    affinity = plugin["spec"]["template"]["spec"]["affinity"]["nodeAffinity"]
    assert affinity["requiredDuringSchedulingIgnoredDuringExecution"][
        "nodeSelectorTerms"
    ][0]["matchExpressions"][0]["values"] == ["ubuntu-gpu-01", "ubuntu-gpu-02"]
    values["config"]["profiles"][0]["node"] = "unregistered-desktop"
    path.write_text(json.dumps(values))
    failed = subprocess.run(
        [
            "helm",
            "template",
            "test",
            str(ROOT / "charts/homelab-inference"),
            "-f",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert failed.returncode != 0
    assert "owned resource flavor" in failed.stderr


def _render(tmp_path, values):
    path = tmp_path / "values.json"
    path.write_text(json.dumps(values))
    return subprocess.run(
        [
            "helm",
            "template",
            "test",
            str(ROOT / "charts/homelab-inference"),
            "-f",
            str(path),
        ],
        capture_output=True,
        text=True,
    )


def test_desktop_quota_opens_the_queue_without_the_gateway(tmp_path):
    base = {
        "workerEnabled": True,
        "devicePluginDigest": "sha256:" + "a" * 64,
        "desktopQuota": True,
    }
    refused = _render(tmp_path, base)
    assert refused.returncode != 0 and "accepted desktop node UID" in refused.stderr
    unmeasured = _render(tmp_path, {**base, "desktopAcceptedNodeUID": "uid"})
    assert (
        unmeasured.returncode != 0 and "measured accepted capacity" in unmeasured.stderr
    )
    result = _render(
        tmp_path,
        {
            **base,
            "desktopAcceptedNodeUID": "uid",
            "measured": {"cpu": 18, "memoryGi": 26, "scratchGi": 20, "gpu": 1},
        },
    )
    assert result.returncode == 0, result.stderr
    docs = [d for d in yaml.safe_load_all(result.stdout) if d]
    assert not any(d["kind"] == "Deployment" for d in docs)  # no batch gateway
    queue = next(d for d in docs if d["kind"] == "ClusterQueue")
    quota = {
        r["name"]: r["nominalQuota"]
        for r in queue["spec"]["resourceGroups"][0]["flavors"][0]["resources"]
    }
    assert quota == {
        "cpu": "12",
        "memory": "24Gi",
        "ephemeral-storage": "20Gi",
        "nvidia.com/gpu": "1",
    }
    assert (
        "admissionChecksStrategy" not in queue["spec"]
        and "admissionChecks" not in queue["spec"]
    )
