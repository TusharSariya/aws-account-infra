"""Prepare a new, offline VM directory. Never operates on an existing VM or boots it."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARTIFACTS = json.loads((ROOT / "artifacts.json").read_text())
DISKS = {"PROTOTYPE-control-plane.qcow2": "24G", "pilot-monitoring.qcow2": "8G"}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_artifacts(directory):
    for name, spec in ARTIFACTS["files"].items():
        if digest(directory / name) != spec["sha256"]:
            raise RuntimeError("Artifact checksum mismatch: " + name)


def prepare(directory, cache=None):
    directory = directory.expanduser().resolve()
    if any((p / ".git").exists() for p in [directory, *directory.parents]):
        raise RuntimeError("VM material must be outside Git")
    # mkdir is exclusive: even an empty existing directory requires explicit review.
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name, spec in ARTIFACTS["files"].items():
        target = directory / name
        if cache:
            shutil.copyfile(cache.expanduser() / name, target)
        else:
            with urllib.request.urlopen(spec["url"], timeout=120) as response:
                with target.open("xb") as output:
                    shutil.copyfileobj(response, output)
        if digest(target) != spec["sha256"]:
            raise RuntimeError("Artifact checksum mismatch: " + name)
        target.chmod(0o700 if name != "metal-amd64.iso" else 0o600)
    for name, size in DISKS.items():
        subprocess.run(
            ["qemu-img", "create", "-f", "qcow2", str(directory / name), size],
            check=True,
        )
        subprocess.run(["qemu-img", "check", str(directory / name)], check=True)
    for name in ["launch.sh", "network-import.sh", "artifacts.json"]:
        shutil.copyfile(ROOT / name, directory / name)
    (directory / "UNCONFIGURED").write_text(
        "New empty disks. No cluster or recovery state installed.\n"
    )
    print("Prepared offline VM directory: " + str(directory))
    print(
        "Follow CREATE-RESTORE.md before booting. No cluster was created or restored."
    )


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--artifact-cache",
        type=Path,
        help="Copy and verify previously downloaded public artifacts",
    )
    parser.add_argument(
        "--check-artifacts",
        action="store_true",
        help="Read-only checksum verification; creates nothing",
    )
    args = parser.parse_args()
    if args.check_artifacts:
        validate_artifacts(args.directory.expanduser())
        print("All pinned public artifacts match")
    else:
        prepare(args.directory, args.artifact_cache)


if __name__ == "__main__":
    main()
