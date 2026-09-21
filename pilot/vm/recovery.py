"""Save or verify private cluster recovery state, without VM disks or an archive."""

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from migrate import VM, talos
from common import BASE, PROFILE, get, identity


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    required = {
        "controlplane.machineconfig.yaml",
        "etcd.snapshot",
        "talosconfig",
        "kubeconfig",
        "nodes.json",
        "volumes.json",
    }
    if not required <= manifest.get("sha256", {}).keys():
        raise RuntimeError("Incomplete recovery manifest")
    if manifest.get("kube_system_uid") != PROFILE["kube_system_uid"]:
        raise RuntimeError("Recovery cluster identity mismatch")
    for name, expected in manifest["sha256"].items():
        path = directory / name
        if (
            Path(name).is_absolute()
            or ".." in Path(name).parts
            or path.is_symlink()
            or not path.resolve().is_relative_to(directory.resolve())
        ):
            raise RuntimeError("Invalid recovery manifest path")
        if checksum(path) != expected:
            raise RuntimeError("Recovery checksum mismatch: " + name)
    print("Recovery file checksums verified; a restore drill is still required")


def backup(directory):
    identity(admin=True)
    directory = directory.expanduser().resolve()
    if any((p / ".git").exists() for p in [directory, *directory.parents]):
        raise RuntimeError("Recovery secrets must be outside Git")
    directory.mkdir(mode=0o700, exist_ok=False)
    config = json.loads(talos("get", "machineconfig", "v1alpha1", "-o", "json"))["spec"]
    if not isinstance(config, str) or not config.strip():
        raise RuntimeError("Unexpected Talos machine configuration representation")
    (directory / "controlplane.machineconfig.yaml").write_text(config)
    talos("etcd", "snapshot", str(directory / "etcd.snapshot"))
    for name in ["talosconfig", "kubeconfig"]:
        shutil.copyfile(VM / "private" / name, directory / name)
    shutil.copytree(BASE / "private", directory / "host-monitoring-private")
    (directory / "nodes.json").write_text(json.dumps(get("nodes", admin=True)))
    (directory / "volumes.json").write_text(json.dumps(get("pv", admin=True)))
    for path in directory.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    manifest = {
        "created": time.time(),
        "kube_system_uid": PROFILE["kube_system_uid"],
        "node": "talos-v93-t3u",
        "guest": "10.0.2.15",
        "includes_vm_disks": False,
        "includes_volume_data": False,
        "sha256": {
            str(p.relative_to(directory)): checksum(p)
            for p in sorted(directory.rglob("*"))
            if p.is_file()
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    check(directory)
    print("Private recovery state saved at " + str(directory))
    print(
        "This local copy does not protect against losing this host. No files were uploaded."
    )


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "check"])
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    {"backup": backup, "check": check}[args.action](args.directory.expanduser())


if __name__ == "__main__":
    main()
