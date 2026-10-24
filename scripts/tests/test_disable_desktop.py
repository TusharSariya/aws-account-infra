import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "disable_desktop", Path(__file__).parents[1] / "disable-desktop.py"
)
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


def fixtures():
    node = {
        "metadata": {"name": "ubuntu-gpu-01", "uid": "accepted"},
        "spec": {
            "taints": [
                {
                    "key": "homelab.tfdraw.dev/compute",
                    "value": "true",
                    "effect": "NoSchedule",
                },
                {"key": "node.kubernetes.io/unreachable", "effect": "NoExecute"},
            ]
        },
    }
    queue = {
        "spec": {
            "resourceGroups": [
                {
                    "flavors": [
                        {
                            "name": "desktop-compute",
                            "resources": [
                                {"name": "cpu", "nominalQuota": "12"},
                                {"name": "memory", "nominalQuota": "24Gi"},
                            ],
                        }
                    ]
                }
            ]
        }
    }
    deploy = {
        "spec": {
            "template": {
                "spec": {"nodeSelector": {"kubernetes.io/hostname": "ubuntu-gpu-01"}}
            }
        }
    }
    return node, queue, deploy


def test_disable_preserves_existing_isolation_and_stops_admission_without_storage_mutation():
    node, queue, dep = fixtures()
    changes = desktop.changes(node, queue, dep, "accepted")
    assert [kind for kind, _, _ in changes] == [
        "nodes",
        "clusterqueues.kueue.x-k8s.io",
        "deployments",
    ]
    assert changes[0][2][0]["value"][:2] == node["spec"]["taints"]
    assert changes[0][2][0]["value"][-1]["key"] == "homelab.tfdraw.dev/quarantine"
    assert [p["value"] for p in changes[1][2]] == ["0", "0", "Hold"]
    assert changes[2][2][0] == {"op": "replace", "path": "/spec/replicas", "value": 0}


def test_replaced_node_is_never_modified():
    with pytest.raises(ValueError, match="identity"):
        desktop.changes(*fixtures(), "different-node")


def test_shared_queue_or_retargeted_deployment_is_not_disabled():
    node, queue, dep = fixtures()
    queue["spec"]["resourceGroups"][0]["flavors"].append({"name": "another-desktop"})
    with pytest.raises(ValueError, match="shared"):
        desktop.changes(node, queue, dep, "accepted")
    node, queue, dep = fixtures()
    dep["spec"]["template"]["spec"]["nodeSelector"]["kubernetes.io/hostname"] = (
        "another-desktop"
    )
    with pytest.raises(ValueError, match="target"):
        desktop.changes(node, queue, dep, "accepted")
