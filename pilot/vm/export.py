"""Export this accepted pilot privately; always restart the source after offline checks."""

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from migrate import (
    BASE,
    ROOT,
    VM,
    identity,
    pause,
    run,
    shutdown,
    verify,
    talos,
    start_vm,
)


def export(destination):
    os.umask(0o077)
    identity(admin=True)
    report = json.loads((BASE / "portable-acceptance.json").read_text())
    if not report["passed"] or time.time() - report["ended"] > 86400:
        raise RuntimeError(
            "Recent complete-stack acceptance, including restart persistence, is required"
        )
    directory = Path(destination).expanduser().resolve()
    # Archives contain full administrative credentials and must never enter a checkout.
    if any((p / ".git").exists() for p in [directory, *directory.parents]):
        raise RuntimeError("Export must be outside every Git checkout")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_mode & 0o077:
        raise RuntimeError("Export directory must have mode 0700")
    if shutil.disk_usage(directory).free < 40 * 1024**3:
        raise RuntimeError(
            "At least 40 GiB free is required for archive and extracted verification"
        )
    archive = directory / (
        "pilot-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".tar.gz"
    )
    if archive.exists():
        raise RuntimeError("Archive already exists")
    current_machine_config = talos("get", "machineconfig", "v1alpha1", "-o", "yaml")
    pause()
    stopped = False
    try:
        shutdown()
        stopped = True
        for disk in ["PROTOTYPE-control-plane.qcow2", "pilot-monitoring.qcow2"]:
            run(["qemu-img", "check", "-f", "qcow2", str(VM / disk)], timeout=300)
        with tempfile.TemporaryDirectory(dir=directory) as staging:
            stage = Path(staging)
            # Copy small inputs only. GNU tar reads both large disks directly while stopped.
            for source, name in [
                (VM / "private", "private"),
                (BASE / "private", "host-monitoring-private"),
            ]:
                shutil.copytree(source, stage / name)
            (stage / "private/current-machineconfig-resource.yaml").write_text(
                current_machine_config
            )
            shutil.copytree(
                ROOT.parent,
                stage / "pilot-platform",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            for filename in ["talosctl", "kubectl"]:
                shutil.copy2(VM / filename, stage / filename)
            for filename in ["launch.sh", "network-import.sh", "IMPORT.md"]:
                shutil.copy2(ROOT / filename, stage / filename)
            shutil.copy2(BASE / "portable-acceptance.json", stage / "acceptance.json")
            shutil.copy2(VM / "network.sh", stage / "source-network.sh")
            (stage / "source-routes.json").write_text(
                run(["ip", "-j", "route", "show"])
            )
            (stage / "source-bridge.json").write_text(
                run(["ip", "-j", "addr", "show", "tp103br"])
            )
            (stage / "qemu-version.txt").write_text(
                run(["qemu-system-x86_64", "--version"])
            )
            (stage / "identity.json").write_text(
                json.dumps(
                    {
                        "kube_system_uid": "507117e6-f7ed-4307-a016-4ecc9a28b519",
                        "guest": "10.0.2.15",
                        "mac": "52:54:00:77:03:01",
                        "monitoring_serial": "PILOT-MONITORING-01",
                        "cpus": 3,
                        "memory_mib": 6144,
                        "single_running_copy": True,
                    },
                    indent=2,
                )
            )
            with (stage / "SHA256SUMS").open("w") as out:
                for filename in [
                    "PROTOTYPE-control-plane.qcow2",
                    "pilot-monitoring.qcow2",
                    "metal-amd64.iso",
                ]:
                    with (VM / filename).open("rb") as stream:
                        digest = hashlib.file_digest(stream, "sha256").hexdigest()
                    out.write(digest + "  " + filename + "\n")
                for path in sorted(stage.rglob("*")):
                    if path.is_file() and path.name != "SHA256SUMS":
                        out.write(
                            hashlib.sha256(path.read_bytes()).hexdigest()
                            + "  "
                            + str(path.relative_to(stage))
                            + "\n"
                        )
            partial = archive.with_suffix(".partial")
            run(
                [
                    "tar",
                    "--sparse",
                    "-czf",
                    str(partial),
                    "-C",
                    str(VM),
                    "PROTOTYPE-control-plane.qcow2",
                    "pilot-monitoring.qcow2",
                    "metal-amd64.iso",
                    "-C",
                    staging,
                    ".",
                ],
                timeout=1800,
            )
            # Verify decompression, member checksums and qcow2 consistency on extracted copies.
            with tempfile.TemporaryDirectory(dir=directory) as check:
                run(["tar", "-xzf", str(partial), "-C", check], timeout=1800)
                run(["sha256sum", "-c", "SHA256SUMS"], cwd=check, timeout=1800)
                for filename in [
                    "PROTOTYPE-control-plane.qcow2",
                    "pilot-monitoring.qcow2",
                ]:
                    run(
                        [
                            "qemu-img",
                            "check",
                            "-f",
                            "qcow2",
                            str(Path(check) / filename),
                        ],
                        timeout=300,
                    )
            partial.rename(archive)
            with archive.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            archive.with_suffix(archive.suffix + ".sha256").write_text(
                digest + "  " + archive.name + "\n"
            )
    finally:
        if stopped:
            start_vm()
            verify()
            # Node readiness alone is insufficient: verify resumed services and old data.
            import sys

            sys.path.insert(0, str(ROOT.parent / "monitoring/kubernetes"))
            from accept import ready, persist

            ready()
            persist(json.loads((BASE / "persistence-proof.json").read_text()))
    print("Private verified archive: " + str(archive))
    print(
        "Source restarted and verified. Cross-host operation is unverified; only one copy may run."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default="~/private-pilot-exports")
    export(parser.parse_args().directory)
