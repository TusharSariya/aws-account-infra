"""Install monitoring after the explicit VM resize; private inputs stay on the host."""

import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import BASE, get, identity, kubectl, run
from access import configure_forwards

ROOT = Path(__file__).resolve().parent
SERVICES = ["prometheus", "loki", "alloy", "grafana", "alertmanager"]


def apply(obj):
    identity(admin=True)
    kubectl("apply", "-f", "-", data=json.dumps(obj), admin=True)


def main():
    os.umask(0o077)
    identity(admin=True)
    from validate import validate, native

    validate()
    native()
    if not (BASE / "migration/resized").exists():
        raise RuntimeError("Run vm/migrate.py resize and verify first")
    nodes = get("nodes", "-l", "node-role.kubernetes.io/control-plane", admin=True)[
        "items"
    ]
    if (
        len(nodes) != 1
        or nodes[0]["status"]["capacity"]["cpu"] != "3"
        or int(nodes[0]["status"]["capacity"]["memory"].removesuffix("Ki"))
        < 5 * 1024**2
    ):
        raise RuntimeError("Control plane has not completed the 3 CPU / 6 GiB resize")
    vm = Path.home() / "talos-wifi-prototype"
    talos = [
        str(vm / "talosctl"),
        "--talosconfig",
        str(vm / "private/talosconfig"),
        "-n",
        "10.0.2.15",
        "-e",
        "10.0.2.15",
    ]
    run(
        [
            *talos,
            "patch",
            "mc",
            "--patch",
            "@" + str(ROOT.parents[1] / "vm/user-volumes.yaml"),
        ],
        timeout=180,
    )
    run(
        [
            *talos,
            "patch",
            "mc",
            "--patch",
            "@" + str(ROOT.parents[1] / "vm/kubelet-tls.yaml"),
        ],
        timeout=180,
    )
    for _ in range(10):
        run(["python3", str(ROOT.parents[1] / "vm/kubelet_tls.py")])
        time.sleep(2)
    # Never bind PVs to a missing mount (which could write to the system disk).
    for name in SERVICES:
        deadline = time.monotonic() + 120
        while True:
            try:
                status = run(
                    [*talos, "get", "volumestatus", "u-pilot-" + name, "-o", "json"]
                )
                if json.loads(status)["spec"]["phase"] == "ready":
                    break
            except subprocess.CalledProcessError:
                # The controller may not have created VolumeStatus yet after patching.
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("Talos volume is not ready: " + name)
            time.sleep(3)
    apply(
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": "pilot-monitoring"},
        }
    )
    private = BASE / "private"
    if not (private / "host.key").exists():
        run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:3072",
                "-nodes",
                "-days",
                "365",
                "-subj",
                "/CN=pilot-host-telemetry",
                "-addext",
                "subjectAltName=IP:10.0.2.2",
                "-keyout",
                str(private / "host.key"),
                "-out",
                str(private / "host.crt"),
            ]
        )
    for name in ["host-token", "grafana-password"]:
        path = private / name
        if not path.exists():
            path.write_text(secrets.token_urlsafe(32))
        path.chmod(0o600)
    for name, data in [
        (
            "host-telemetry",
            {
                "token": (private / "host-token").read_text(),
                "ca.crt": (private / "host.crt").read_text(),
            },
        ),
        ("grafana-admin", {"password": (private / "grafana-password").read_text()}),
    ]:
        apply(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": name, "namespace": "pilot-monitoring"},
                "stringData": data,
            }
        )
    backup = BASE / "migration/host-source"
    if not backup.exists():
        shutil.copytree(BASE / "source", backup)
    for filename in ["exporter.py", "common.py", "profile.json"]:
        shutil.copy2(ROOT.parent / filename, BASE / "source" / filename)
    (BASE / "kubernetes-mode").touch()
    run(["systemctl", "--user", "stop", *["pilot-" + name for name in SERVICES]])
    run(["systemctl", "--user", "restart", "pilot-exporter"])
    identity(admin=True)
    # Do not allow Kustomize namespace transformers to change the scoped log-reader Roles.
    kubectl("apply", "-k", str(ROOT), admin=True)
    for name in SERVICES:
        kubectl(
            "rollout",
            "status",
            "deployment/" + name,
            "-n",
            "pilot-monitoring",
            "--timeout=900s",
            admin=True,
            timeout=930,
        )
    configure_forwards()
    print("Run measure.py and acceptance.py before disabling the old host units")


if __name__ == "__main__":
    main()
