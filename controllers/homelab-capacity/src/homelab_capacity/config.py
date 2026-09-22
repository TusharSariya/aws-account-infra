"""Fixed retained-host identities. No caller-selected node/IP/VM arguments."""

import json
from pathlib import Path

INVENTORY = {
    "primary": {
        "node": "talos-worker-01",
        "pve": "10.0.0.224",
        "talos": "10.0.0.222",
        "vm": 102,
        "system_uuid": "2ae5ec87-3879-4a3a-a90d-ca017642dbe8",
        "node_uid": "09343bc7-dd2e-4d8e-81f2-d1201f2fb28f",
    },
    "secondary": {
        "node": "talos-worker-02",
        "pve": "10.0.0.223",
        "talos": "10.0.0.225",
        "vm": 103,
        "system_uuid": "58203485-9d12-4205-9345-ca4e96148c65",
        "node_uid": "ebdb565b-0d91-4663-8751-2f239ec2f745",
    },
}


def load(path):
    path = Path(path).expanduser()
    if path.stat().st_mode & 0o077:
        raise PermissionError("Coordinator configuration must be private")
    config = json.loads(path.read_text())
    idle = config.get("idle_seconds", 1800)
    if type(idle) is not int or not 60 <= idle <= 86400:
        raise ValueError("idle_seconds must be an integer from 60 to 86400")
    config["idle_seconds"] = idle
    if set(config["modes"]) != set(INVENTORY) or any(
        m not in {"observe", "wake", "automatic"} for m in config["modes"].values()
    ):
        raise ValueError("Explicit rollout mode required for each registered host")
    return config
