import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "hold", Path(__file__).parents[1] / "homelab-power-hold.py"
)
hold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hold)


def test_node_ready_is_not_enough_during_platform_restoration():
    node = {
        "metadata": {
            "annotations": {"homelab.tfdraw.dev/power-operation": "in-progress"}
        },
        "spec": {},
        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
    }
    nexus = {"status": {"availableReplicas": 1}}
    assert not hold.restored([node], nexus)
    node["metadata"]["annotations"] = {"homelab.tfdraw.dev/power-intent": "blocked"}
    assert not hold.restored([node], nexus)
    node["metadata"]["annotations"] = {}
    assert hold.restored([node], nexus)
    assert not hold.restored([node], {})


def test_freeze_requires_acknowledgement_for_every_host_and_same_identity():
    lease = {
        "metadata": {
            "uid": "current",
            "labels": {"homelab.tfdraw.dev/power-hold": "true"},
            "annotations": {
                "homelab.tfdraw.dev/hold-mode": "freeze",
                "homelab.tfdraw.dev/frozen-primary": "current",
            },
        }
    }
    assert not hold.freeze_acknowledged(lease, "current", ["primary", "secondary"])
    lease["metadata"]["annotations"]["homelab.tfdraw.dev/frozen-secondary"] = "current"
    assert hold.freeze_acknowledged(lease, "current", ["primary", "secondary"])
    assert not hold.freeze_acknowledged(lease, "old", ["primary"])
    lease["metadata"]["labels"]["homelab.tfdraw.dev/power-hold"] = "false"
    assert not hold.freeze_acknowledged(lease, "current", ["primary"])


def test_failed_critical_operation_cannot_release_freeze(tmp_path, monkeypatch):
    import json
    import sys

    import pytest

    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"freeze": True}))
    monkeypatch.setattr(
        sys,
        "argv",
        ["hold", "release", "--kubeconfig", "unused", "--receipt", str(receipt)],
    )
    monkeypatch.setattr(
        hold.subprocess, "run", lambda *a, **kw: pytest.fail("must not contact API")
    )
    with pytest.raises(RuntimeError, match="verified completion"):
        hold.main()
