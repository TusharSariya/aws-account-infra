"""Run the existing bounded load suite, sampling capacity without changing workers."""

import json
import os
import subprocess
import time
from pathlib import Path

from capacity import swapping

from common import (
    BASE,
    CONTROLLERS,
    PROFILE,
    identity,
    memory,
    run,
    vmstat,
    get,
    kubectl,
)


def sample():
    guest = {}
    if (BASE / "kubernetes-mode").exists():
        nodes = get("nodes", "-l", "node-role.kubernetes.io/control-plane", admin=True)[
            "items"
        ]
        if len(nodes) != 1:
            raise RuntimeError("Expected one management node")
        stats = json.loads(
            kubectl(
                "get",
                "--raw",
                "/api/v1/nodes/"
                + nodes[0]["metadata"]["name"]
                + "/proxy/stats/summary",
                admin=True,
            )
        )
        pods = get("pods", "-A", admin=True)["items"]
        selected = [
            p
            for p in pods
            if p["metadata"]["namespace"] in ["pilot-monitoring", "pilot-argocd"]
        ]
        guest = {
            "kubernetes_controllers": {
                name: get("deployment", name, "-n", ns, admin=True)
                .get("status", {})
                .get("availableReplicas", 0)
                >= 1
                for ns, name in [
                    ("kueue-system", "prototype-kueue-controller-manager"),
                    ("prototype-slot", "prototype-binpack"),
                    ("prototype-slot", "prototype-slot-ca"),
                ]
            },
            "guest_available": stats["node"]["memory"]["availableBytes"],
            "ooms": sum(
                1
                for p in selected
                for c in p["status"].get("containerStatuses", [])
                if any(
                    c.get(k, {}).get("terminated", {}).get("reason") == "OOMKilled"
                    for k in ["state", "lastState"]
                )
            ),
            "pods_ready": bool(selected)
            and all(
                any(
                    c["type"] == "Ready" and c["status"] == "True"
                    for c in p["status"].get("conditions", [])
                )
                for p in selected
            ),
        }
    return {
        **guest,
        "time": time.time(),
        "page_size": os.sysconf("SC_PAGE_SIZE"),
        "available": memory()["MemAvailable"],
        "swap": {k: vmstat()[k] for k in ["pswpin", "pswpout"]},
        "controllers": {
            u: run(
                ["systemctl", "--user", "show", u, "-p", "ActiveState", "--value"]
            ).strip()
            for u in CONTROLLERS
        },
    }


def main():
    identity(admin=True)
    (BASE / "measurement.json").unlink(missing_ok=True)
    started = time.time()
    samples = [sample()]
    log = BASE / "bounded-load.log"
    with log.open("w") as output:
        process = subprocess.Popen(
            [
                "python3",
                str(Path.home() / "kubernetes-validation/suite.py"),
                "run",
                "--scenarios",
                "smoke,load-bursts,load-sustained",
            ],
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            while process.poll() is None:
                time.sleep(15)
                samples.append(sample())
                print(json.dumps(samples[-1]), flush=True)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=240)
    no_swap = samples[-1]["swap"] == samples[0]["swap"]
    paging = swapping(samples)
    passed = (
        process.returncode == 0
        and paging["no_sustained_swap"]
        and all(all(v == "active" for v in s["controllers"].values()) for s in samples)
        and min(s["available"] for s in samples) >= 512 * 1024**2
        and all(
            s.get("guest_available", 512 * 1024**2) >= 512 * 1024**2
            and s.get("ooms", 0) == 0
            and s.get("pods_ready", True)
            and all(s.get("kubernetes_controllers", {}).values())
            for s in samples
        )
    )
    report = {
        "mode": "kubernetes" if (BASE / "kubernetes-mode").exists() else "host",
        "kube_system_uid": PROFILE["kube_system_uid"],
        "started": started,
        "ended": time.time(),
        "passed": passed,
        "load_returncode": process.returncode,
        "no_swap": no_swap,
        "paging": paging,
        "samples": samples,
    }
    (BASE / "measurement.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "samples"}))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
