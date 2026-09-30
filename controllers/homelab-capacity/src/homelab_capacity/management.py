"""Fixed-address direct management, independent of application DNS and proxies."""

import json
from pathlib import Path
import subprocess
from .config import INVENTORY
from .imm2 import PowerController
from .errors import RetryObservation, UncertainShutdown


def command(argv, *, operation, shutdown=False, timeout=90):
    """Keep operation/exit category, never captured credentials or server output."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        error = UncertainShutdown if shutdown else RetryObservation
        raise error(f"{operation}: client deadline exceeded") from None
    if result.returncode:
        error = (
            UncertainShutdown
            if shutdown
            else (RetryObservation if result.returncode == 255 else RuntimeError)
        )
        raise error(f"{operation}: command exited {result.returncode}")
    return result


class Management:
    def __init__(self, config):
        self.config = config

    def power(self, host):
        return PowerController(Path(self.config["power_config"]).expanduser(), host)

    def pve(self, host, action="status"):
        if action not in {"status", "start-worker", "poweroff"}:
            raise ValueError("Unsupported management action")
        node = INVENTORY[host]
        result = command(
            [
                "ssh",
                "-F",
                "/dev/null",
                "-o",
                "BatchMode=yes",
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "IdentityAgent=none",
                "-o",
                "UserKnownHostsFile="
                + str(Path(self.config["known_hosts"]).expanduser()),
                "-i",
                str(Path(self.config["pve_key"]).expanduser()),
                "root@" + node["pve"],
                action,
            ],
            operation="Proxmox " + action,
            shutdown=action == "poweroff",
            timeout=110,
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            error = UncertainShutdown if action == "poweroff" else RetryObservation
            raise error(f"Proxmox {action}: incomplete response") from None
        if data["vm"] != node["vm"] or data["uuid"] != node["system_uuid"]:
            raise RuntimeError("Proxmox VM identity mismatch")
        return data

    def talos(self, host, *args):
        node = INVENTORY[host]
        result = command(
            [
                str(Path(self.config["talosctl"]).expanduser()),
                "--talosconfig",
                str(Path(self.config["talosconfig"]).expanduser()),
                "-e",
                node["talos"],
                "-n",
                node["talos"],
                *args,
            ],
            operation="Talos " + args[0],
            shutdown=args[0] == "shutdown",
            timeout=90,
        )
        return result.stdout

    def storage(self, host):
        if host != "primary":
            return {}
        volume = json.loads(
            self.talos(
                host, "get", "volumestatus", "u-local-path-provisioner", "-o", "json"
            )
        )["spec"]
        mount = json.loads(
            self.talos(
                host, "get", "mountstatus", "u-local-path-provisioner", "-o", "json"
            )
        )["spec"]
        if (
            volume["phase"] != "ready"
            or mount["target"] != "/var/mnt/local-path-provisioner"
        ):
            raise RuntimeError("Primary storage is not mounted")
        return {
            k: volume[k]
            for k in ["uuid", "partitionUUID", "location", "filesystem", "size"]
        }
