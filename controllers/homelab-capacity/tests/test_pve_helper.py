"""Exercise the deployed forced-command helper against simulated Proxmox commands."""

import importlib.util
from pathlib import Path
import subprocess

import pytest

HELPER = Path(__file__).resolve().parents[3] / "platform/automatic-power/pve-helper.py"
spec = importlib.util.spec_from_file_location("pve_helper", HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def test_autostart_wins_between_status_and_start(monkeypatch):
    calls = []

    def status(*args):
        calls.append(args)
        assert args == ("qm", "status", "102")
        return "status: running\n"

    def start(args, **kwargs):
        calls.append(tuple(args))
        raise subprocess.CalledProcessError(255, args, stderr="VM 102 already running")

    monkeypatch.setattr(helper, "run", status)
    monkeypatch.setattr(helper.subprocess, "run", start)
    assert helper.start_worker(102, "stopped") == "running"
    assert calls == [("qm", "start", "102"), ("qm", "status", "102")]


def test_failed_start_is_not_hidden_if_worker_still_stopped(monkeypatch):
    monkeypatch.setattr(helper, "run", lambda *args: "status: stopped\n")

    def start(args, **kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(helper.subprocess, "run", start)
    with pytest.raises(subprocess.CalledProcessError):
        helper.start_worker(102, "stopped")
