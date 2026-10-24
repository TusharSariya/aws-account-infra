import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "power_deploy", ROOT / "platform/automatic-power/deploy.py"
)
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def payload():
    files = {
        name: "# valid source\n"
        for name in deploy.EXTRAS | {deploy.PACKAGE + "coordinator.py"}
    }
    return {
        "revision": "a" * 40,
        "files": files,
        "hashes": {n: deploy.digest(s) for n, s in files.items()},
    }


def test_accepts_complete_checksummed_source():
    data = payload()
    assert deploy.validate(data) == data["files"]


def test_accepts_actual_repository_source_payload():
    data = payload()
    files = {
        p.relative_to(ROOT).as_posix(): p.read_text()
        for p in (ROOT / deploy.PACKAGE).glob("*.py")
    }
    files.update({name: (ROOT / name).read_text() for name in deploy.EXTRAS})
    data["files"] = files
    data["hashes"] = {name: deploy.digest(source) for name, source in files.items()}
    assert deploy.PACKAGE + "imm2.py" in files
    assert deploy.validate(data) == files


@pytest.mark.parametrize(
    "path",
    ["../../.ssh/authorized_keys", deploy.PACKAGE + "../evil.py", "/tmp/evil.py"],
)
def test_rejects_paths_outside_exact_deployment_scope(path):
    data = payload()
    data["files"][path] = ""
    data["hashes"][path] = deploy.digest("")
    with pytest.raises(ValueError, match="path"):
        deploy.validate(data)


def test_rejects_corruption_before_touching_live_installation():
    data = payload()
    data["files"][deploy.PACKAGE + "coordinator.py"] += "# changed\n"
    with pytest.raises(ValueError, match="checksum"):
        deploy.validate(data)


def test_rejects_incomplete_deployment():
    data = payload()
    del data["files"][deploy.PACKAGE + "coordinator.py"]
    with pytest.raises(ValueError, match="Incomplete"):
        deploy.validate(data)


def receiver(
    tmp_path, monkeypatch, *, pending=None, acknowledged=True, fail_helper=False
):
    import contextlib
    import json
    import sys
    from types import SimpleNamespace

    monkeypatch.setattr(deploy.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(deploy.time, "sleep", lambda _: None)
    config = tmp_path / ".config/homelab-capacity"
    config.mkdir(parents=True)
    power = config / "hosts.json"
    power.write_text(json.dumps({"lock_dir": str(tmp_path / "locks")}))
    (config / "coordinator.json").write_text(json.dumps({"power_config": str(power)}))
    source = tmp_path / ".local/share/homelab-capacity/retained/src/homelab_capacity"
    source.mkdir(parents=True)
    (source / "coordinator.py").write_text("# old\n")
    protection = {
        "pending": pending,
        "holds": {"ci-freeze-test": {"acknowledged": acknowledged}},
    }

    class Lock:
        def __init__(self, *_):
            pass

        def locked(self):
            return contextlib.nullcontext()

        def read(self):
            return protection

    monkeypatch.setitem(
        sys.modules, "homelab_capacity.interlock", SimpleNamespace(Interlock=Lock)
    )
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        if fail_helper and args[0] == "python3":
            raise RuntimeError("helper unavailable")
        return SimpleNamespace(
            stdout=deploy.digest("# valid source\n") + " helper.py\n"
        )

    monkeypatch.setattr(deploy, "run", run)
    return source, calls, protection


@pytest.mark.parametrize(
    "pending,ack", [(None, False), ({"action": "mains-off"}, True)]
)
def test_receiver_refuses_unacknowledged_or_unsettled_hosts(
    tmp_path, monkeypatch, pending, ack
):
    source, calls, _ = receiver(
        tmp_path, monkeypatch, pending=pending, acknowledged=ack
    )
    with pytest.raises(RuntimeError, match="acknowledged"):
        deploy.receive(payload())
    assert not calls
    assert (source / "coordinator.py").read_text() == "# old\n"


def test_receiver_verifies_both_helpers_before_recording_revision(
    tmp_path, monkeypatch
):
    import json

    source, calls, protection = receiver(tmp_path, monkeypatch)
    deploy.receive(payload())
    assert (source / "coordinator.py").read_text() == "# valid source\n"
    assert len([call for call in calls if call[0] == "ssh"]) == 2
    receipt = json.loads(
        (tmp_path / ".local/share/homelab-capacity/deployed.json").read_text()
    )
    assert receipt["revision"] == "a" * 40
    assert protection["holds"]  # only the verified CI release may remove protection


def test_helper_failure_restarts_service_and_leaves_freeze_without_success_receipt(
    tmp_path, monkeypatch
):
    _, calls, protection = receiver(tmp_path, monkeypatch, fail_helper=True)
    with pytest.raises(RuntimeError, match="helper unavailable"):
        deploy.receive(payload())
    assert ("systemctl", "--user", "start", "homelab-coordinator.service") in calls
    assert protection["holds"]
    assert not (tmp_path / ".local/share/homelab-capacity/deployed.json").exists()
