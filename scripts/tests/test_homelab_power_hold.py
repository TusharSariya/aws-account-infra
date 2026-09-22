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
