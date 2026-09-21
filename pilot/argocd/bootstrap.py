"""Capacity-gated, management-only, non-HA Argo CD bootstrap for the pilot."""

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "monitoring"))
from common import BASE, get, identity, kubectl, memory  # noqa: E402

ROOT = Path(__file__).resolve().parent


def quantity(value):
    for suffix, factor in [
        ("Ki", 1024),
        ("Mi", 1024**2),
        ("Gi", 1024**3),
        ("m", 0.001),
    ]:
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * factor
    return float(value)


def capacity(samples):
    # 1536 MiB is the sum of the four active container memory limits.
    return bool(samples) and all(
        s["management_available"] >= 2048 * 1024**2
        and s["management_cpu_free"] >= 0.9
        and s["request_memory_free"] >= 1536 * 1024**2
        and s["request_cpu_free"] >= 0.9
        and s["laptop_available"] >= 512 * 1024**2
        for s in samples
    )


def gate():
    identity(admin=True)
    report = json.loads((BASE / "measurement.json").read_text())
    if (BASE / "kubernetes-mode").exists() and report.get("mode") != "kubernetes":
        raise RuntimeError(
            "Monitoring in Kubernetes needs its own passing load measurement"
        )
    if not report["passed"] or not 0 <= time.time() - report["ended"] <= 86400:
        raise RuntimeError("A passing bounded-load measurement within 24h is required")
    with urllib.request.urlopen(
        "http://127.0.0.1:3000/api/health", timeout=5
    ) as response:
        if json.load(response)["database"] != "ok":
            raise RuntimeError("Grafana must be healthy before the Argo CD stage")
    with urllib.request.urlopen("http://127.0.0.1:9093/-/ready", timeout=5) as response:
        if response.status != 200:
            raise RuntimeError("Alertmanager must be ready before the Argo CD stage")
    nodes = get("nodes", "-l", "node-role.kubernetes.io/control-plane", admin=True)[
        "items"
    ]
    if len(nodes) != 1:
        raise RuntimeError("Expected exactly one pilot management node")
    node = nodes[0]
    name = node["metadata"]["name"]
    pods = get("pods", "-A", "--field-selector", "spec.nodeName=" + name, admin=True)[
        "items"
    ]
    requested = {"cpu": 0, "memory": 0}
    for pod in pods:
        if pod["status"].get("phase") in ["Succeeded", "Failed"]:
            continue
        for key in requested:
            regular = sum(
                quantity(c.get("resources", {}).get("requests", {}).get(key, "0"))
                for c in pod["spec"]["containers"]
            )
            init = max(
                [
                    quantity(c.get("resources", {}).get("requests", {}).get(key, "0"))
                    for c in pod["spec"].get("initContainers", [])
                ]
                or [0]
            )
            requested[key] += max(regular, init) + quantity(
                pod["spec"].get("overhead", {}).get(key, "0")
            )
    samples = []
    for index in range(5):
        identity(admin=True)
        stats = json.loads(
            kubectl(
                "get",
                "--raw",
                "/api/v1/nodes/" + name + "/proxy/stats/summary",
                admin=True,
            )
        )["node"]
        samples.append(
            {
                "time": time.time(),
                "management_available": stats["memory"]["availableBytes"],
                "management_cpu_free": quantity(node["status"]["allocatable"]["cpu"])
                - stats["cpu"]["usageNanoCores"] / 1e9,
                "request_memory_free": quantity(node["status"]["allocatable"]["memory"])
                - requested["memory"],
                "request_cpu_free": quantity(node["status"]["allocatable"]["cpu"])
                - requested["cpu"],
                "laptop_available": memory()["MemAvailable"],
            }
        )
        print(json.dumps(samples[-1]), flush=True)
        if index < 4:
            time.sleep(15)
    evidence = {
        "time": time.time(),
        "passed": capacity(samples),
        "samples": samples,
        "required_management_available_bytes": 2048 * 1024**2,
        "reason": "1536 MiB active Argo CD limits plus 512 MiB management reserve; 650m requests plus 250m CPU reserve",
    }
    (BASE / "argocd-capacity.json").write_text(json.dumps(evidence, indent=2) + "\n")
    if not evidence["passed"]:
        raise RuntimeError(
            "Argo CD blocked: insufficient measured management capacity; no resources changed"
        )


def bootstrap():
    gate()
    for filename, item in json.loads((ROOT / "release.json").read_text())[
        "files"
    ].items():
        if (
            hashlib.sha256((ROOT / "vendor" / filename).read_bytes()).hexdigest()
            != item["sha256"]
        ):
            raise RuntimeError("Argo CD vendor checksum mismatch")
    identity(admin=True)
    kubectl("apply", "-f", str(ROOT / "namespace.yaml"), admin=True)
    for crd in sorted((ROOT / "vendor").glob("*-crd.yaml")):
        identity(admin=True)
        kubectl("apply", "--server-side", "-f", str(crd), admin=True)
    identity(admin=True)
    kubectl("apply", "-k", str(ROOT), "-n", "pilot-argocd", admin=True)
    identity(admin=True)
    kubectl("apply", "-f", str(ROOT / "access.yaml"), admin=True)
    identity(admin=True)
    kubectl("apply", "-f", str(ROOT / "project.yaml"), admin=True)
    for kind, name in [
        ("deployment", "argocd-server"),
        ("deployment", "argocd-repo-server"),
        ("deployment", "argocd-redis"),
        ("statefulset", "argocd-application-controller"),
    ]:
        kubectl(
            "rollout",
            "status",
            kind + "/" + name,
            "-n",
            "pilot-argocd",
            "--timeout=180s",
            admin=True,
            timeout=240,
        )
    print(
        "Argo CD ready; manual sync only. Application requires a reviewed Git digest."
    )


def configure_repository(token_file):
    identity(admin=True)
    if token_file is None:
        raise RuntimeError(
            "Private Git repository requires --repository-token-file with a repository-scoped read-only token; no resources changed"
        )
    credentials = Path(token_file).expanduser()
    if credentials.stat().st_mode & 0o077:
        raise RuntimeError("Repository token file must be readable only by its owner")
    token = credentials.read_text().strip()
    if not token:
        raise RuntimeError("Repository token file is empty")
    identity(admin=True)
    kubectl(
        "apply",
        "-f",
        "-",
        admin=True,
        data=json.dumps(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": "pilot-git-repository",
                    "namespace": "pilot-argocd",
                    "labels": {"argocd.argoproj.io/secret-type": "repository"},
                },
                "stringData": {
                    "type": "git",
                    "url": "https://github.com/TusharSariyaOrg/aws-account-infra.git",
                    "username": "x-access-token",
                    "password": token,
                },
            }
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "install", "repository"])
    parser.add_argument(
        "--repository-token-file",
        help="Private 0600 file containing a repository-scoped read-only Git token",
    )
    args = parser.parse_args()
    if args.action == "check":
        gate()
    elif args.action == "repository":
        configure_repository(args.repository_token_file)
    else:
        bootstrap()
