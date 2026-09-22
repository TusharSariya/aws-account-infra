#!/usr/bin/env python3
"""Root-owned forced-command endpoint for one retained VM. No arbitrary argv."""

import json
import os
from pathlib import Path
import re
import subprocess


def run(*args):
    return subprocess.check_output(args, text=True, timeout=20)


def main():
    if os.geteuid() != 0:
        raise RuntimeError("Root-owned endpoint required")
    action = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    if action not in {"status", "start-worker", "poweroff"}:
        raise ValueError("Unsupported retained-host operation")
    config = json.loads(Path("/etc/homelab-power.json").read_text())
    vm = config["vm"]
    if vm not in {102, 103}:
        raise ValueError("Only registered worker VMs are permitted")
    vmconfig = run("qm", "config", str(vm))
    match = re.search(r"^smbios1: .*?uuid=([0-9a-f-]+)", vmconfig, re.M)
    if not match or match.group(1) != config["system_uuid"]:
        raise ValueError("Worker identity changed")
    resources = json.loads(
        run(
            "pvesh",
            "get",
            "/cluster/resources",
            "--type",
            "vm",
            "--output-format",
            "json",
        )
    )
    running = [o["vmid"] for o in resources if o.get("status") == "running"]
    worker = next(o for o in resources if o["vmid"] == vm and o["type"] == "qemu")
    if vm == 102:
        source = run("qm", "config", "100")
        if (
            100 in running
            or not re.search(r"^onboot: 0$", source, re.M)
            or not re.search(r"^protection: 1$", source, re.M)
        ):
            raise ValueError("Retired control-plane source is not fenced")
    # Modern systemd records even this non-interactive SSH session in utmp.
    # Exclude only our own process ancestry, never sessions merely sharing an IP.
    ancestors, pid = set(), os.getpid()
    while pid > 1:
        ancestors.add(pid)
        status = Path(f"/proc/{pid}/status").read_text()
        pid = int(re.search(r"^PPid:\s+(\d+)", status, re.M).group(1))
    sessions = run("who", "-u").splitlines()
    users = False
    for line in sessions:
        fields = line.split()
        session_pid = (
            fields[-2] if fields and fields[-1].startswith("(") else fields[-1]
        )
        if not session_pid.isdigit() or int(session_pid) not in ancestors:
            users = True
    if action == "start-worker":
        if worker["status"] == "stopped":
            subprocess.run(
                ["qm", "start", str(vm)],
                check=True,
                timeout=90,
                stdout=subprocess.DEVNULL,
            )
        elif worker["status"] != "running":
            raise RuntimeError("Unknown worker state")
    elif action == "poweroff":
        if running or users:
            raise RuntimeError(
                "Running guests or interactive users block host shutdown"
            )
        # A short fixed timer lets SSH deliver its acknowledgement before systemd
        # tears down the network. This never forces power off or retries a request.
        subprocess.run(
            [
                "systemd-run",
                "--unit=homelab-retained-poweroff",
                "--on-active=3s",
                "/usr/bin/systemctl",
                "poweroff",
            ],
            check=True,
            timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    print(
        json.dumps(
            {
                "vm": vm,
                "uuid": match.group(1),
                "status": worker["status"],
                "other_running": [v for v in running if v != vm],
                "users": users,
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Avoid echoing raw management output or configuration to the caller.
        raise SystemExit("Retained-host operation failed; inspect host locally")
