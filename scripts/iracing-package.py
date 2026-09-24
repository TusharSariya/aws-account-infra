"""Deterministic, locked Lambda artifact builder for OpenTofu external data."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def export_requirements(app, requirements):
    # Validate project metadata against its canonical index without fetching.
    # CI's dependency cache changes UV_INDEX_URL, not the committed lock identity.
    environment = dict(os.environ, UV_INDEX_URL="https://pypi.org/simple")
    subprocess.run(["uv", "lock", "--check", "--offline", "--directory", str(app)],
                   env=environment, check=True, stdout=sys.stderr)
    subprocess.run(["uv", "export", "--directory", str(app), "--frozen", "--no-dev",
                    "--no-emit-project", "--output-file", str(requirements)],
                   check=True, stdout=sys.stderr)


def main():
    query = json.load(sys.stdin)
    root = Path(query["root"]).resolve()
    app = root / "apps/lambda/python/3.14/iracing-calendar"
    output = root / "build/lambda/iracing-calendar"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        requirements = stage / "requirements.txt"
        export_requirements(app, requirements)
        vendor = stage / "vendor"
        subprocess.run(["uv", "pip", "install", "--python-version", "3.14", "--python-platform",
                        "aarch64-manylinux_2_28", "--only-binary", ":all:", "--require-hashes",
                        "--target", str(vendor), "-r", str(requirements)], check=True, stdout=sys.stderr)
        archive = stage / "app.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
            for source, prefix in ((vendor, ""), (app / "iracing_calendar", "iracing_calendar/")):
                for path in sorted(source.rglob("*")):
                    if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                        continue
                    relative = path.relative_to(source).as_posix()
                    if relative.endswith(("/RECORD", "/direct_url.json")) or relative.startswith("bin/"):
                        continue
                    info = zipfile.ZipInfo(prefix + relative, date_time=(2020, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o644 << 16
                    package.writestr(info, path.read_bytes())
        data = archive.read_bytes()
        digest = hashlib.sha256(data).digest()
        target = output / (digest.hex() + ".zip")
        target.write_bytes(data)
    print(json.dumps({"path": str(target), "sha256": digest.hex(),
                      "base64sha256": base64.b64encode(digest).decode()}))


if __name__ == "__main__":
    main()
