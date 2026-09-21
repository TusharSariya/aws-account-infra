"""Checkpointed resize of the existing pilot. No privilege escalation or disk deletion."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "monitoring"))
from common import BASE, CONTROLLERS, PROFILE, get, identity, kubectl, run

ROOT = Path(__file__).resolve().parent
VM = Path.home() / "talos-wifi-prototype"
STATE = BASE / "migration"
SERVICES = [
    "pilot-" + n for n in ["prometheus", "loki", "alloy", "grafana", "alertmanager"]
]


def talos(*args):
    return run(
        [
            str(VM / "talosctl"),
            "--talosconfig",
            str(VM / "private/talosconfig"),
            "-n",
            "10.0.2.15",
            "-e",
            "10.0.2.15",
            *args,
        ],
        timeout=180,
    )


def start_vm(legacy=False):
    """Keep QEMU's launch diagnostic visible without exposing unrelated command output."""
    try:
        return run(["bash", str(VM / "boot.sh"), *(["routed"] if legacy else [])])
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            "VM launch failed: " + (error.stderr or "no diagnostic").strip()
        ) from error


def checkpoint():
    identity(admin=True)
    if (STATE / "before.json").exists():
        raise RuntimeError(
            "Checkpoint already exists; use resume or rollback, never overwrite it"
        )
    STATE.mkdir(parents=True, mode=0o700, exist_ok=True)
    nodes = get("nodes", admin=True)["items"]
    state = {
        "uid": PROFILE["kube_system_uid"],
        "controllers": {
            u: run(
                ["systemctl", "--user", "show", u, "-p", "ActiveState", "--value"]
            ).strip()
            for u in CONTROLLERS
        },
        "ready_nodes": [
            n["metadata"]["name"]
            for n in nodes
            if any(
                c["type"] == "Ready" and c["status"] == "True"
                for c in n["status"]["conditions"]
            )
        ],
        "slots": {
            name: {
                "paused": (Path(s["state"]).expanduser() / "maintenance").exists(),
                "desired": (Path(s["state"]).expanduser() / "desired.json").read_text(),
            }
            for name, s in PROFILE["slots"].items()
        },
    }
    (STATE / "before.json").write_text(json.dumps(state, indent=2))
    shutil.copy2(VM / "boot.sh", STATE / "boot.sh")
    shutil.copy2(VM / "network.sh", STATE / "network.sh")
    (STATE / "default-target").write_text(run(["systemctl", "get-default"]))
    (STATE / "nodes.json").write_text(json.dumps(nodes))
    (STATE / "storage.json").write_text(kubectl("get", "pv", "-o", "json", admin=True))
    talos("etcd", "snapshot", str(STATE / "etcd.snapshot"))


def pause():
    active = {
        u: run(
            ["systemctl", "--user", "show", u, "-p", "ActiveState", "--value"]
        ).strip()
        for u in CONTROLLERS
    }
    run(["systemctl", "--user", "stop", *CONTROLLERS, *SERVICES], timeout=90)
    # A fresh outage checkpoint avoids comparing later restarts with retired load-test workers.
    nodes = get("nodes", admin=True)["items"]
    state = {
        "controllers": active,
        "ready_nodes": [
            n["metadata"]["name"]
            for n in nodes
            if any(
                c["type"] == "Ready" and c["status"] == "True"
                for c in n["status"]["conditions"]
            )
        ],
        "slots": {
            name: {
                "paused": (Path(s["state"]).expanduser() / "maintenance").exists(),
                "desired": (Path(s["state"]).expanduser() / "desired.json").read_text(),
            }
            for name, s in PROFILE["slots"].items()
        },
    }
    (STATE / "outage.json").write_text(json.dumps(state, indent=2))


def shutdown():
    pid = int((VM / "qemu.pid").read_text())
    talos("shutdown", "--wait=false")
    end = time.monotonic() + 180
    while Path(f"/proc/{pid}").exists():
        if time.monotonic() > end:
            raise RuntimeError("Graceful shutdown timed out; will not force-stop QEMU")
        time.sleep(2)


def verify():
    end = time.monotonic() + 300
    while True:
        try:
            identity(admin=True)
            from kubelet_tls import approve

            approve()
            nodes = get("nodes", admin=True)["items"]
            ready = {
                n["metadata"]["name"]
                for n in nodes
                if any(
                    c["type"] == "Ready" and c["status"] == "True"
                    for c in n["status"]["conditions"]
                )
            }
            before = json.loads((STATE / "outage.json").read_text())
            if not set(before["ready_nodes"]) <= ready:
                raise RuntimeError(
                    "Previously ready workers/control plane have not recovered"
                )
            for name, s in PROFILE["slots"].items():
                directory = Path(s["state"]).expanduser()
                if (directory / "maintenance").exists() != before["slots"][name][
                    "paused"
                ] or (directory / "desired.json").read_text() != before["slots"][name][
                    "desired"
                ]:
                    raise RuntimeError("Worker pause/desired state changed")
            break
        except Exception:
            if time.monotonic() > end:
                raise
            time.sleep(5)
    for ns, name in [
        ("kueue-system", "prototype-kueue-controller-manager"),
        ("prototype-slot", "prototype-binpack"),
        ("prototype-slot", "prototype-slot-ca"),
    ]:
        kubectl(
            "rollout",
            "status",
            "deployment/" + name,
            "-n",
            ns,
            "--timeout=120s",
            admin=True,
            timeout=150,
        )
    original_volumes = json.loads((STATE / "storage.json").read_text())["items"]
    current_volumes = {
        v["metadata"]["name"]: v["metadata"]["uid"]
        for v in get("pv", admin=True)["items"]
    }
    if any(
        current_volumes.get(v["metadata"]["name"]) != v["metadata"]["uid"]
        for v in original_volumes
    ):
        raise RuntimeError("Existing storage-proof PV identity changed")
    for unit, active in before["controllers"].items():
        if active == "active":
            run(["systemctl", "--user", "start", unit])
    if run(["systemctl", "get-default"]) != (STATE / "default-target").read_text():
        raise RuntimeError("Host boot default changed")


def resize():
    if os.geteuid() == 0:
        raise RuntimeError("Run as the pilot user, never root")
    if (
        run(
            ["systemctl", "show", "display-manager", "-p", "ActiveState", "--value"]
        ).strip()
        == "active"
    ):
        raise RuntimeError("Run resize-root.sh through interactive SSH first")
    if not os.access("/dev/kvm", os.R_OK | os.W_OK):
        raise RuntimeError("Interactive resize-root.sh is required for KVM access")
    disk = VM / "pilot-monitoring.qcow2"
    if disk.exists():
        raise RuntimeError("Unexpected monitoring disk; refusing to overwrite")
    if shutil.disk_usage(VM).free < 10 * 1024**3:
        raise RuntimeError("At least 10 GiB free disk is required")
    identity(admin=True)
    if not (
        Path(PROFILE["slots"]["secondary"]["state"]).expanduser() / "maintenance"
    ).exists():
        raise RuntimeError("Expected the secondary to remain intentionally paused")
    checkpoint()
    pause()
    shutdown()
    try:
        run(["qemu-img", "create", "-f", "qcow2", str(disk), "8G"])
        shutil.copy2(ROOT / "launch.sh", VM / "boot.sh")
        start_vm()
    except Exception:
        # QEMU launch/create failure while offline: restore only the launch configuration.
        restore_stopped()
        raise
    verify()
    (STATE / "resized").touch()
    print("Identity, workers and controllers verified; reconciliation restored")


def resume():
    """Resume only the checkpointed resize after a launch permission failure."""
    if os.geteuid() == 0 or not os.access("/dev/kvm", os.R_OK | os.W_OK):
        raise RuntimeError("Run as the pilot user after the interactive KVM helper")
    if not (STATE / "outage.json").exists() or not (STATE / "boot.sh").exists():
        raise RuntimeError("No paused resize checkpoint")
    pidfile = VM / "qemu.pid"
    if pidfile.exists() and Path("/proc/" + pidfile.read_text().strip()).exists():
        raise RuntimeError("VM process exists; refusing to start a second copy")
    for filename in ["PROTOTYPE-control-plane.qcow2", "pilot-monitoring.qcow2"]:
        run(["qemu-img", "check", "-f", "qcow2", str(VM / filename)], timeout=180)
    info = json.loads(
        run(["qemu-img", "info", "--output=json", str(VM / "pilot-monitoring.qcow2")])
    )
    if info["virtual-size"] != 8 * 1024**3 or info.get("backing-filename"):
        raise RuntimeError("Unexpected monitoring disk geometry or backing file")
    shutil.copy2(ROOT / "launch.sh", VM / "boot.sh")
    start_vm()
    verify()
    (STATE / "resized").touch()
    print(
        "Resumed resize; original identity, workers, storage and controllers verified"
    )


def retry():
    """Retry a rolled-back migration using its original checkpoint and retained disks."""
    identity(admin=True)
    if (
        not (STATE / "before.json").exists()
        or (STATE / "resized").exists()
        or (BASE / "kubernetes-mode").exists()
    ):
        raise RuntimeError("Retry requires a completed rollback checkpoint")
    if not os.access("/dev/kvm", os.R_OK | os.W_OK):
        raise RuntimeError("Interactive KVM preparation is required")
    if (
        run(
            ["systemctl", "show", "display-manager", "-p", "ActiveState", "--value"]
        ).strip()
        == "active"
    ):
        raise RuntimeError("Stop the desktop with the interactive helper first")
    if not (VM / "pilot-monitoring.qcow2").is_file():
        raise RuntimeError("Retained monitoring disk is missing")
    pause()
    shutdown()
    try:
        resume()
    except Exception:
        pidfile = VM / "qemu.pid"
        if (
            not pidfile.exists()
            or not Path("/proc/" + pidfile.read_text().strip()).exists()
        ):
            restore_stopped()
        raise


def restore_stopped():
    pidfile = VM / "qemu.pid"
    if pidfile.exists() and Path("/proc/" + pidfile.read_text().strip()).exists():
        raise RuntimeError("VM process still exists; refusing offline rollback")
    if not (STATE / "boot.sh").exists():
        raise RuntimeError("No original launch checkpoint")
    shutil.copy2(STATE / "boot.sh", VM / "boot.sh")
    start_vm(legacy=True)
    verify()


def detach_monitoring_volumes():
    """Remove only monitoring mount declarations; retain all partition data."""
    status = talos("get", "volumestatus")
    ids = {row.split()[3] for row in status.splitlines()[1:] if len(row.split()) >= 4}
    documents = [
        "apiVersion: v1alpha1\nkind: UserVolumeConfig\nname: "
        + name
        + "\n$patch: delete\n"
        for name in SERVICES
        if "u-" + name in ids
    ]
    if documents:
        talos("patch", "mc", "--mode=no-reboot", "--patch", "---\n".join(documents))


def rollback():
    identity(admin=True)
    # Keep the failed gate evidence before removing its active acceptance record.
    evidence = STATE / (
        "rollback-evidence-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    )
    evidence.mkdir(mode=0o700)
    for name in ["measurement.json", "bounded-load.log", "portable-acceptance.json"]:
        if (BASE / name).exists():
            shutil.copy2(BASE / name, evidence / name)
    for ns in ["pilot-argocd", "pilot-monitoring"]:
        if ns in [
            n["metadata"]["name"] for n in get("namespaces", admin=True)["items"]
        ]:
            kubectl(
                "scale",
                "deployment,statefulset",
                "--all",
                "--replicas=0",
                "-n",
                ns,
                admin=True,
            )
            kubectl(
                "wait",
                "--for=delete",
                "pod",
                "--all",
                "-n",
                ns,
                "--timeout=180s",
                admin=True,
                timeout=200,
            )
    detach_monitoring_volumes()
    pause()
    shutdown()
    shutil.copy2(STATE / "boot.sh", VM / "boot.sh")
    start_vm(legacy=True)
    verify()
    (STATE / "resized").unlink(missing_ok=True)
    (BASE / "portable-acceptance.json").unlink(missing_ok=True)
    (BASE / "measurement.json").unlink(missing_ok=True)
    # Restore original host exporter and units if the Kubernetes bridge was installed.
    (BASE / "kubernetes-mode").unlink(missing_ok=True)
    backup = STATE / "host-source"
    if backup.exists():
        shutil.copytree(backup, BASE / "source", dirs_exist_ok=True)
    for unit in (Path.home() / ".config/systemd/user").glob("pilot-forward-*.service"):
        run(["systemctl", "--user", "disable", "--now", unit.name])
    run(["systemctl", "--user", "enable", *SERVICES])
    run(["systemctl", "--user", "restart", "pilot-exporter", *SERVICES])
    deadline = time.monotonic() + 180
    endpoints = [
        (9090, "/-/ready"),
        (3100, "/ready"),
        (12345, "/-/ready"),
        (3000, "/api/health"),
        (9093, "/-/ready"),
    ]
    while True:
        try:
            for port, path in endpoints:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}{path}", timeout=10
                ) as response:
                    if response.status != 200:
                        raise RuntimeError("Host monitoring health failed")
            break
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(3)
    print(
        "Rollback verified: original VM, cluster identity, controllers and host monitoring restored"
    )


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=["resize", "resume", "retry", "verify", "rollback", "restore-stopped"],
    )
    args = parser.parse_args()
    {
        "resize": resize,
        "resume": resume,
        "retry": retry,
        "verify": verify,
        "rollback": rollback,
        "restore-stopped": restore_stopped,
    }[args.action]()
