"""Fixed-address direct management, independent of application DNS and proxies."""

import json
from pathlib import Path
import subprocess
from .config import INVENTORY
from .imm2 import PowerController


class Management:
    def __init__(self, config):
        self.config = config

    def power(self, host):
        return PowerController(Path(self.config["power_config"]).expanduser(), host)

    def pve(self, host, action="status"):
        if action not in {"status", "start-worker", "poweroff"}:
            raise ValueError("Unsupported management action")
        node = INVENTORY[host]
        result = subprocess.run(
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
            capture_output=True,
            text=True,
            timeout=110,
        )
        if result.returncode:
            raise RuntimeError("Restricted Proxmox operation failed")
        data = json.loads(result.stdout)
        if data["vm"] != node["vm"] or data["uuid"] != node["system_uuid"]:
            raise RuntimeError("Proxmox VM identity mismatch")
        return data

    def talos(self, host, *args):
        node = INVENTORY[host]
        result = subprocess.run(
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
            capture_output=True,
            text=True,
            timeout=90,
        )
        if result.returncode:
            raise RuntimeError("Talos operation failed")
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
