"""Exercise the actual forced-command helper without running host commands."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "tasks,allowed", [([], True), ([{"upid": "backup-task"}], False), ({}, False)]
)
def test_active_or_unknown_tasks_block_poweroff(monkeypatch, tasks, allowed):
    path = (
        Path(__file__).resolve().parents[3] / "platform/automatic-power/pve-helper.py"
    )
    spec = importlib.util.spec_from_file_location("pve_helper", path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    monkeypatch.setattr(helper.os, "geteuid", lambda: 0)
    monkeypatch.setattr(helper.os, "getpid", lambda: 1)
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "poweroff")
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self: (
            json.dumps({"vm": 103, "system_uuid": "aaaa-bbbb"})
            if str(self) == "/etc/homelab-power.json"
            else "boot-id"
        ),
    )

    def run(*args):
        if args[0] == "qm":
            return "smbios1: uuid=aaaa-bbbb"
        if args[0] == "pvesh":
            return json.dumps([{"vmid": 103, "type": "qemu", "status": "stopped"}])
        if args[0] == "who":
            return ""
        assert args == (
            "pvenode",
            "task",
            "list",
            "--source",
            "active",
            "--output-format",
            "json",
        )
        return json.dumps(tasks)

    monkeypatch.setattr(helper, "run", run)
    calls = []
    monkeypatch.setattr(
        helper.subprocess, "run", lambda *args, **kwargs: calls.append(args)
    )
    if allowed:
        helper.main()
        assert calls[0][0][-1] == "poweroff"
    else:
        with pytest.raises((RuntimeError, ValueError, TypeError)):
            helper.main()
        assert calls == []
