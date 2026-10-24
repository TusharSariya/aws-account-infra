#!/usr/bin/env python3
"""Root-owned forced-command endpoint for one retained VM. No arbitrary argv."""

import json
import os
import re
import subprocess
from pathlib import Path


def run(*args):
    return subprocess.check_output(args, text=True, timeout=20)


def start_worker(vm, status):
    """Autostart and the coordinator may race; judge the observed postcondition."""
    if status == "running":
        return status
    if status != "stopped":
        raise RuntimeError("Unknown worker state")
    try:
        subprocess.run(
            ["qm", "start", str(vm)],
            check=True,
            timeout=90,
            stdout=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Never match human stderr or assume a failed acknowledgement means the
        # VM did not start. A direct observation also avoids pvestatd's cache.
        if run("qm", "status", str(vm)).strip() == "status: running":
            return "running"
        raise
    if run("qm", "status", str(vm)).strip() != "status: running":
        raise RuntimeError("Worker start has not reached running")
    return "running"


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
    match = re.search(r"^smbios1: .*?uuid=([0-9a-f-]+)", vmconfig, re.MULTILINE)
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
            or not re.search(r"^onboot: 0$", source, re.MULTILINE)
            or not re.search(r"^protection: 1$", source, re.MULTILINE)
        ):
            raise ValueError("Retired control-plane source is not fenced")
    # Modern systemd records even this non-interactive SSH session in utmp.
    # Exclude only our own process ancestry, never sessions merely sharing an IP.
    ancestors, pid = set(), os.getpid()
    while pid > 1:
        ancestors.add(pid)
        status = Path(f"/proc/{pid}/status").read_text()
        pid = int(re.search(r"^PPid:\s+(\d+)", status, re.MULTILINE).group(1))
    sessions = run("who", "-u").splitlines()
    users = False
    for line in sessions:
        fields = line.split()
        session_pid = (
            fields[-2] if fields and fields[-1].startswith("(") else fields[-1]
        )
        if not session_pid.isdigit() or int(session_pid) not in ancestors:
            users = True
    tasks = json.loads(
        run("pvenode", "task", "list", "--source", "active", "--output-format", "json")
    )
    if not isinstance(tasks, list):
        raise TypeError("Proxmox task inventory unavailable")
    active_tasks = [task["upid"] for task in tasks]
    if action == "start-worker":
        worker["status"] = start_worker(vm, worker["status"])
    elif action == "poweroff":
        if running or users or active_tasks:
            raise RuntimeError(
                "Running guests, users or active tasks block host shutdown"
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
                "active_tasks": active_tasks,
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - suppress potentially sensitive management output
        # Avoid echoing raw management output or configuration to the caller.
        raise SystemExit("Retained-host operation failed; inspect host locally")
