"""Pinned pilot identity and bounded subprocess access; no production fallback."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = Path.home() / ".local/share/pilot-monitoring"
PROFILE = json.loads((ROOT / "profile.json").read_text())
CONTROLLERS = [
    "prototype-slot-provider",
    "prototype-slot-placement",
    "prototype-consolidation",
    "prototype-primary-lifecycle",
]


def run(args, **kwargs):
    return subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=True,
        timeout=kwargs.pop("timeout", 45),
        **kwargs,
    ).stdout


def kubectl(*args, admin=False, data=None, timeout=45):
    config = (
        Path(PROFILE["kubeconfig"]).expanduser()
        if admin
        else BASE / "private/reader.kubeconfig"
    )
    return run(
        [
            str(Path(PROFILE["kubectl"]).expanduser()),
            "--kubeconfig",
            str(config),
            "--request-timeout=15s",
            *args,
        ],
        input=data,
        timeout=timeout,
    )


def get(resource, *args, admin=False):
    return json.loads(kubectl("get", resource, *args, "-o", "json", admin=admin))


def identity(admin=False):
    ns = get("namespace", "kube-system", admin=admin)
    if ns["metadata"]["uid"] != PROFILE["kube_system_uid"]:
        raise RuntimeError("Pilot cluster UID mismatch; refusing operation")
    cfg = json.loads(kubectl("config", "view", "--minify", "-o", "json", admin=admin))
    if cfg["clusters"][0]["cluster"]["server"] != PROFILE["server"]:
        raise RuntimeError("Pilot API address mismatch; refusing operation")


def memory():
    return {
        k: int(v.strip().split()[0]) * 1024
        for k, v in (
            line.split(":", 1)
            for line in Path("/proc/meminfo").read_text().splitlines()
        )
    }


def vmstat():
    return {
        k: int(v)
        for k, v in (
            line.split() for line in Path("/proc/vmstat").read_text().splitlines()
        )
    }
