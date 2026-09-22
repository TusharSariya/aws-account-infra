"""CLI compatibility for capacity checks shared with the always-on coordinator."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "retained_capacity",
    ROOT / "controllers/homelab-capacity/src/homelab_capacity/capacity.py",
)
_capacity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_capacity)
quantity = _capacity.quantity
requests = _capacity.requests
verify_storage = _capacity.verify_storage


def verify(node, pods, reserve, pool=None):
    if pool is None:
        import yaml

        pool = yaml.safe_load(
            (
                ROOT / "config/environments/kubernetes/homelab-ci/pool-values.yaml"
            ).read_text()
        )
    return _capacity.verify(node, pods, reserve, pool)
