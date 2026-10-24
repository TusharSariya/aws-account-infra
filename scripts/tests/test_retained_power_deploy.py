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
