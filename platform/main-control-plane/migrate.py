#!/usr/bin/env python3
"""Laptop-side, journaled offline migration of VM 100. Never bootstraps Talos."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

STATE = Path.home() / ".local/share/main-control-plane"
VM = Path("/var/lib/main-control-plane/vm")
PRIVATE = STATE / "private"
SSH = [
    "ssh",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "-i",
    str(Path.home() / ".ssh/main-proxmox"),
    "root@10.0.0.224",
]
K = [
    str(PRIVATE / "kubectl"),
    "--kubeconfig",
    str(PRIVATE / "kubeconfig"),
    "--request-timeout=30s",
]
T = [
    str(PRIVATE / "talosctl"),
    "--talosconfig",
    str(PRIVATE / "talosconfig"),
    "-e",
    "10.0.0.221",
    "-n",
    "10.0.0.221",
]


def run(args, **kw):
    return subprocess.run(args, check=True, text=True, **kw)


def remote(cmd):
    return run(SSH + [cmd], capture_output=True).stdout


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n")
    path.chmod(0o600)


def identities():
    result = {}
    for kind in ["nodes", "namespaces", "pv", "pvc"]:
        items = json.loads(
            run(K + ["get", kind, "-A", "-o", "json"], capture_output=True).stdout
        )["items"]
        result[kind] = {
            o["metadata"].get("namespace", "") + "/" + o["metadata"]["name"]: {
                "uid": o["metadata"]["uid"],
                **(
                    {
                        "volumeName": o["spec"].get("volumeName"),
                        "storageClassName": o["spec"].get("storageClassName"),
                    }
                    if kind == "pvc"
                    else {}
                ),
                **(
                    {
                        "claimRef": o["spec"].get("claimRef"),
                        "nodeAffinity": o["spec"].get("nodeAffinity"),
                    }
                    if kind == "pv"
                    else {}
                ),
            }
            for o in items
        }
    return result


def preflight():
    assert remote("qm status 100").strip() == "status: running"
    config = remote("qm config 100")
    for line in ["bios: ovmf", "cores: 2", "memory: 4096", "scsihw: virtio-scsi-pci"]:
        assert line in config, line
    assert "02:42:00:00:01:00" in config
    assert "vm-100-disk-1" in config and "vm-100-disk-0" in config
    assert Path("/var/lib/main-control-plane/network-proven").exists(), (
        "Wi-Fi proof missing"
    )
    assert shutil.disk_usage(VM).free > 15 * 1024**3, (
        "Need at least 15 GiB before sparse export sizing"
    )
    assert (STATE / "firmware-proven.json").exists(), "Firmware probe missing"
    firmware = json.loads((STATE / "firmware-proven.json").read_text())
    assert firmware["passed"] is True
    assert (
        firmware["code_sha256"]
        == remote(
            "sha256sum /usr/share/pve-edk2-firmware/OVMF_CODE_4M.secboot.fd"
        ).split()[0]
    )
    # Thin allocated extents bound nonzero source data before stopping the source.
    size, percent = map(
        float,
        remote(
            "lvs --noheadings --units b --nosuffix -o lv_size,data_percent /dev/pve/vm-100-disk-1"
        ).split(),
    )
    copy_budget = int(size * percent / 100 * 1.2) + 10 * 1024**3
    assert shutil.disk_usage(VM).free > copy_budget, (
        "Insufficient destination space; leave source running"
    )
    assert int(remote("df --output=avail -B1 /root").splitlines()[-1]) > copy_budget, (
        "Insufficient source export space; leave source running"
    )
    assert not (STATE / "cutover.json").exists(), (
        "Existing cutover journal: do not repeat migration"
    )
    assert shutil.disk_usage(VM).free > 20 * 1024**3, (
        "Retain at least 20 GiB free for copy and recovery"
    )
    assert not (VM / "system.qcow2").exists(), "Never overwrite an existing destination"
    assert (
        subprocess.run(
            ["systemctl", "is-enabled", "main-control-plane.service"],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == "disabled"
    )
    return config


def capture():
    checkpoint = STATE / "recovery"
    checkpoint.mkdir(mode=0o700)  # refuse overwrite
    (checkpoint / "source.conf").write_text(remote("qm config 100"))
    (checkpoint / "source-command.txt").write_text(remote("qm showcmd 100 --pretty"))
    write(checkpoint / "identities.json", identities())
    for name in ["kubeconfig", "talosconfig", "talos-secrets.yaml"]:
        shutil.copy2(PRIVATE / name, checkpoint / name)
    run(T + ["etcd", "snapshot", str(checkpoint / "etcd.snapshot")])
    for resource in [
        "deployments",
        "statefulsets",
        "cronjobs",
        "validatingwebhookconfigurations",
        "mutatingwebhookconfigurations",
    ]:
        (checkpoint / (resource + ".json")).write_text(
            run(K + ["get", resource, "-A", "-o", "json"], capture_output=True).stdout
        )
    write(
        checkpoint / "checksums.json",
        {p.name: digest(p) for p in checkpoint.iterdir() if p.is_file()},
    )


def stop_pilot():
    # Preserve pilot state outside Git; no disk deletion and no bootstrap.
    archive = STATE / "pilot-retired"
    archive.mkdir(mode=0o700)
    units = run(
        ["systemctl", "--user", "list-unit-files", "--no-legend", "--no-pager"],
        capture_output=True,
    ).stdout
    names = [
        line.split()[0]
        for line in units.splitlines()
        if line.startswith(("prototype-", "pilot-")) and ".service" in line.split()[0]
    ]
    (archive / "unit-files.txt").write_text(units)
    for name in names:
        (archive / name).write_text(
            run(["systemctl", "--user", "cat", name], capture_output=True).stdout
        )
    if names:
        run(["systemctl", "--user", "disable", "--now", *names])
    source = Path.home() / "talos-wifi-prototype"
    shutil.copytree(source / "private", archive / "private")
    for name in ["launch.sh", "boot.sh", "network.sh"]:
        if (source / name).exists():
            shutil.copy2(source / name, archive / name)
    run(
        [
            str(source / "talosctl"),
            "--talosconfig",
            str(source / "private/talosconfig"),
            "-e",
            "10.0.2.15",
            "-n",
            "10.0.2.15",
            "etcd",
            "snapshot",
            str(archive / "etcd.snapshot"),
        ]
    )
    run(
        [
            str(source / "talosctl"),
            "--talosconfig",
            str(source / "private/talosconfig"),
            "-e",
            "10.0.2.15",
            "-n",
            "10.0.2.15",
            "shutdown",
            "--wait=false",
        ]
    )
    pid = int((source / "qemu.pid").read_text())
    deadline = time.monotonic() + 180
    while Path(f"/proc/{pid}").exists():
        if time.monotonic() > deadline:
            raise RuntimeError("Pilot did not stop gracefully")
        time.sleep(2)
    # Disk hashes taken only while stopped. Pilot files remain at original paths.
    write(
        archive / "disk-checksums.json",
        {str(p): digest(p) for p in source.glob("*.qcow2")},
    )


def cutover():
    preflight()
    capture()
    stop_pilot()
    write(
        STATE / "cutover.json",
        {"phase": "source-running", "destination_started": False},
    )
    # Fence autostart before graceful shutdown. Never force-stop on timeout.
    remote("qm set 100 --onboot 0 --protection 1")
    remote("qm shutdown 100 --timeout 180")
    assert remote("qm status 100").strip() == "status: stopped"
    write(
        STATE / "cutover.json",
        {"phase": "source-stopped", "destination_started": False},
    )
    # Conversion and qemu-img measure are strictly offline.
    remote("install -d -m 700 /root/main-control-plane-export")
    remote(
        "qemu-img convert -f raw -O qcow2 -S 4k /dev/pve/vm-100-disk-1 /root/main-control-plane-export/system.qcow2"
    )
    remote(
        "qemu-img compare -f raw -F qcow2 /dev/pve/vm-100-disk-1 /root/main-control-plane-export/system.qcow2"
    )
    remote(
        "cp /usr/share/pve-edk2-firmware/OVMF_CODE_4M.secboot.fd /root/main-control-plane-export/OVMF_CODE.fd"
    )
    # The PVE pflash blockdev exposes 540672 bytes of a 4-MiB LV; preserve both.
    remote(
        "dd if=/dev/pve/vm-100-disk-0 of=/root/main-control-plane-export/efidisk-full.raw status=none"
    )
    remote(
        "head -c 540672 /root/main-control-plane-export/efidisk-full.raw > /root/main-control-plane-export/OVMF_VARS.fd"
    )
    allocated = int(
        remote("stat -c %s /root/main-control-plane-export/system.qcow2").strip()
    )
    assert shutil.disk_usage(VM).free > allocated + 10 * 1024**3, (
        "Sparse copy will exhaust laptop disk"
    )
    finish_copy()


def finish_copy():
    journal = json.loads((STATE / "cutover.json").read_text())
    assert journal == {"phase": "source-stopped", "destination_started": False}, (
        "Copy resume is prohibited after any destination launch"
    )
    assert remote("qm status 100").strip() == "status: stopped"
    assert not Path("/var/lib/main-control-plane/source-fenced").exists()
    assert (
        subprocess.run(
            ["fuser", str(VM / "system.qcow2")], check=False, capture_output=True
        ).returncode
        != 0
    ), "A process still has the destination disk open"
    hashes = {}
    ssh_command = (
        "ssh -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -i "
        + str(Path.home() / ".ssh/main-proxmox")
    )
    for name in ["system.qcow2", "OVMF_CODE.fd", "OVMF_VARS.fd", "efidisk-full.raw"]:
        target = VM / name
        run(
            [
                "rsync",
                "-az",
                "--partial",
                "--append-verify",
                "--timeout=120",
                "-e",
                ssh_command,
                "root@10.0.0.224:/root/main-control-plane-export/" + name,
                str(target),
            ]
        )
        target.chmod(0o600)
        hashes[name] = digest(target)
        assert (
            hashes[name]
            == remote("sha256sum /root/main-control-plane-export/" + name).split()[0]
        )
    write(
        VM / "copy.json",
        {"source_stopped": True, "virtual_size": 100 * 1024**3, "sha256": hashes},
    )
    write(
        STATE / "cutover.json",
        {"phase": "destination-starting", "destination_started": True},
    )
    run(["sudo", "-n", "/usr/local/lib/main-control-plane/ops.sh", "activate"])
    print("Destination started. Acceptance and ownership retirement remain mandatory.")


def verify():
    before = json.loads((STATE / "recovery/identities.json").read_text())
    after = identities()
    for kind, entries in before.items():
        for key, value in entries.items():
            assert after[kind].get(key) == value, (
                kind,
                key,
                "identity or binding changed",
            )
    run(T + ["etcd", "members"])
    run(K + ["get", "--raw=/readyz?verbose"])
    run(K + ["wait", "node/talos-cp-01", "--for=condition=Ready", "--timeout=180s"])
    print(
        "Identity, binding and API checks passed; complete the documented network, capacity, sleep and reboot gates."
    )


if __name__ == "__main__":
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=["preflight", "capture", "cutover", "finish_copy", "verify"]
    )
    args = parser.parse_args()
    globals()[args.action]()
