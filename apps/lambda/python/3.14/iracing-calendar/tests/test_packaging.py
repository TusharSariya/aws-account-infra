"""Exercise the real release export under the CI dependency-cache override."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[6]
APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "package_builder", ROOT / "scripts/iracing-package.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_export_with_ci_index_preserves_lock_and_rejects_stale_metadata(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    for filename in ("pyproject.toml", "uv.lock"):
        shutil.copyfile(APP / filename, project / filename)
    original = (project / "uv.lock").read_bytes()
    monkeypatch.setenv("UV_INDEX_URL", "http://127.0.0.1:1/pypi/simple/")
    monkeypatch.setenv("UV_OFFLINE", "true")
    requirements = tmp_path / "requirements.txt"
    builder.export_requirements(project, requirements)
    assert "--hash=sha256:" in requirements.read_text()
    assert (project / "uv.lock").read_bytes() == original
    metadata = project / "pyproject.toml"
    metadata.write_text(
        metadata.read_text().replace('"boto3>=1.40,<2"', '"boto3>=99,<100"')
    )
    with pytest.raises(subprocess.CalledProcessError):
        builder.export_requirements(project, tmp_path / "stale.txt")
    assert not (tmp_path / "stale.txt").exists()
