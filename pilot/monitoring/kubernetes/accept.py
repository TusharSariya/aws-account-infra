"""Complete-stack acceptance: fresh load, log/alert proofs, Pod and VM persistence."""

import argparse
import json
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vm"))
from common import BASE, get, identity, kubectl, run
from acceptance import alerts, dashboards, logs, request, wait_for
from migrate import pause, shutdown, verify, start_vm

ROOT = Path(__file__).resolve().parent
NAMES = ["prometheus", "loki", "alloy", "grafana", "alertmanager"]


def ready(include_argocd=True):
    for namespace in ["pilot-monitoring"] + (
        ["pilot-argocd"] if include_argocd else []
    ):
        for deployment in get("deployment", "-n", namespace, admin=True)["items"]:
            if deployment["spec"].get("replicas", 1):
                kubectl(
                    "rollout",
                    "status",
                    "deployment/" + deployment["metadata"]["name"],
                    "-n",
                    namespace,
                    "--timeout=240s",
                    admin=True,
                    timeout=270,
                )
    if include_argocd:
        kubectl(
            "rollout",
            "status",
            "statefulset/argocd-application-controller",
            "-n",
            "pilot-argocd",
            "--timeout=240s",
            admin=True,
            timeout=270,
        )
    wait_for(
        lambda: request(
            "http://127.0.0.1:9090/api/v1/query?query=pilot_collection_success"
        )["data"]["result"][0]["value"][1]
        == "1"
    )


def persist(proof):
    query = urllib.parse.urlencode(
        {"query": "pilot_collection_success", "time": proof["time"]}
    )
    wait_for(
        lambda: request("http://127.0.0.1:9090/api/v1/query?" + query)["data"][
            "result"
        ][0]["value"][1]
        == "1"
    )
    wait_for(lambda: request(proof["log_url"])["data"]["result"])
    dashboards()
    current = {
        p["metadata"]["name"]: p["spec"]["volumeName"]
        for p in get("pvc", "-n", "pilot-monitoring", admin=True)["items"]
    }
    if current != proof["claims"]:
        raise RuntimeError("Claim mapping changed across replacement/restart")


def main(monitoring_only=False):
    identity(admin=True)
    report_name = (
        "monitoring-acceptance.json" if monitoring_only else "portable-acceptance.json"
    )
    (BASE / report_name).unlink(missing_ok=True)
    if monitoring_only:
        report = json.loads((BASE / "measurement.json").read_text())
        if not (
            report.get("passed")
            and report.get("mode") == "kubernetes"
            and 0 <= time.time() - report["ended"] <= 86400
        ):
            raise RuntimeError(
                "Fresh passing Kubernetes monitoring measurement required"
            )
        namespaces = get("namespaces", admin=True)["items"]
        if any(n["metadata"]["name"] == "pilot-argocd" for n in namespaces):
            raise RuntimeError("Argo is present; use complete-stack acceptance")
    else:
        # Complete-stack acceptance must not accidentally bless monitoring alone.
        get(
            "statefulset",
            "argocd-application-controller",
            "-n",
            "pilot-argocd",
            admin=True,
        )
        print("Running complete-stack bounded load and capacity checks", flush=True)
        # Stream the safe capacity evidence so failures explain the rejected gate.
        subprocess.run(
            ["python3", str(ROOT.parent / "measure.py")], check=True, timeout=2400
        )
    print("Checking logs, dashboards and alert firing/resolution", flush=True)
    logs()
    dashboards()
    alerts()
    proof = {
        "time": time.time(),
        "claims": {
            p["metadata"]["name"]: p["spec"]["volumeName"]
            for p in get("pvc", "-n", "pilot-monitoring", admin=True)["items"]
        },
        "log_url": "http://127.0.0.1:3100/loki/api/v1/query_range?"
        + urllib.parse.urlencode(
            {
                "query": '{namespace="prototype-slot"} |= "pilot-observe"',
                "start": str(int((time.time() - 1800) * 1e9)),
                "end": str(int(time.time() * 1e9)),
            }
        ),
    }
    (BASE / "persistence-proof.json").write_text(json.dumps(proof, indent=2))
    print("Replacing monitoring Pods and checking retained data", flush=True)
    identity(admin=True)
    for name in NAMES:
        kubectl(
            "delete",
            "pod",
            "-n",
            "pilot-monitoring",
            "-l",
            "app=" + name,
            "--wait=true",
            admin=True,
            timeout=120,
        )
        kubectl(
            "rollout",
            "status",
            "deployment/" + name,
            "-n",
            "pilot-monitoring",
            "--timeout=240s",
            admin=True,
            timeout=270,
        )
    ready(include_argocd=not monitoring_only)
    persist(proof)
    complete_after_pod_replacement(proof, monitoring_only)


def complete_after_pod_replacement(proof, monitoring_only=False):
    """Finish restart verification after the saved Pod-replacement proof passes."""
    identity(admin=True)
    report_name = (
        "monitoring-acceptance.json" if monitoring_only else "portable-acceptance.json"
    )
    print("Restarting the VM with lifecycle reconciliation paused", flush=True)
    pause()
    shutdown()
    start_vm()
    verify()
    ready(include_argocd=not monitoring_only)
    persist(proof)
    print("Checking alert delivery after VM restart", flush=True)
    alerts()
    # Verify capacity again after the restart (without another full load run).
    from measure import sample

    final = sample()
    if (
        final["available"] < 512 * 1024**2
        or final["guest_available"] < 512 * 1024**2
        or final["ooms"]
        or not final["pods_ready"]
        or not all(final["kubernetes_controllers"].values())
        or not all(v == "active" for v in final["controllers"].values())
    ):
        raise RuntimeError("Post-restart capacity or Pod health failed")
    run(["systemctl", "--user", "disable", *["pilot-" + n for n in NAMES]])
    report = {
        "passed": True,
        "argocd_included": not monitoring_only,
        "ended": time.time(),
        "pod_replacement": True,
        "vm_restart": True,
        "logs_after_deletion": True,
        "alert_firing_resolution": True,
        "dashboard": True,
        "final_capacity": final,
    }
    (BASE / report_name).write_text(json.dumps(report, indent=2) + "\n")
    print(
        ("Monitoring" if monitoring_only else "Full stack")
        + " acceptance passed; record current private recovery state"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--monitoring-only",
        action="store_true",
        help="Verify monitoring persistence using its fresh passing load report; Argo must be absent",
    )
    main(parser.parse_args().monitoring_only)
