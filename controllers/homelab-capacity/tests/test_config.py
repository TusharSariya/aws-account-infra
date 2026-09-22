import json
from types import SimpleNamespace

import pytest

from homelab_capacity.config import load
from homelab_capacity.coordinator import Coordinator
from homelab_capacity.journal import Journal
from homelab_capacity.lifecycle import State


@pytest.mark.parametrize("idle", [0, -1, 59, 86401, True, 300.5, "300"])
def test_invalid_idle_is_rejected(tmp_path, idle):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "modes": {"primary": "observe", "secondary": "observe"},
                "idle_seconds": idle,
            }
        )
    )
    path.chmod(0o600)
    with pytest.raises(ValueError, match="idle_seconds"):
        load(path)


def test_idle_change_restarts_timer_without_interrupting_recovery(tmp_path):
    config = {"modes": {"primary": "wake", "secondary": "wake"}, "idle_seconds": 1800}
    controller = Coordinator(
        config,
        kube=SimpleNamespace(),
        management=SimpleNamespace(),
        journal=Journal(tmp_path),
    )
    controller.states["primary"] = State(phase="idle", idle_since=50)
    controller.states["secondary"] = State(
        phase="waking", pending="await-on", deadline=1250
    )
    controller.reconfigure(config | {"idle_seconds": 300})
    assert controller.states["primary"].idle_since is None
    assert controller.states["secondary"].pending == "await-on"
    assert controller.states["secondary"].deadline == 1250
    assert controller.config["idle_seconds"] == 300
