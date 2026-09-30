"""Bounded kubectl adapter. Never print captured Kubernetes object bodies."""

import base64
import json
import ssl
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import INVENTORY
from .errors import RetryObservation


def operation_error(result, operation):
    diagnostic = (result.stdout + result.stderr).lower()
    # Inspect captured text for categories but never put it in public diagnostics.
    if any(
        marker in diagnostic
        for marker in (
            "(conflict)",
            "object has been modified",
            "test failed",
            "timed out",
            "timeout",
            "connection refused",
            "connection reset",
            "serviceunavailable",
            "too many requests",
            "unexpected eof",
        )
    ):
        return RetryObservation(
            f"Kubernetes {operation}: transient conflict/transport (exit {result.returncode})"
        )
    return RuntimeError(f"Kubernetes {operation}: rejected (exit {result.returncode})")


RESOURCES = {
    "pods": "pods",
    "replicasets": "replicasets",
    "jobs": "jobs",
    "workloads": "workloads.kueue.x-k8s.io",
    "backups": "backups.postgresql.cnpg.io",
    "applications": "applications.argoproj.io",
    "nodes": "nodes",
    "deployments": "deployments",
    "statefulsets": "statefulsets",
    "daemonsets": "daemonsets",
    "cronjobs": "cronjobs",
    "clusters": "clusters.postgresql.cnpg.io",
    "pv": "pv",
    "pvc": "pvc",
    "leases": "leases.coordination.k8s.io",
    "runners": "ephemeralrunners.actions.github.com",
}


class Kube:
    def __init__(self, config):
        self.command = [
            str(Path(config["kubectl"]).expanduser()),
            "--kubeconfig",
            str(Path(config["kubeconfig"]).expanduser()),
            "--request-timeout=20s",
        ]

    def run(self, *args, data=None):
        try:
            result = subprocess.run(
                self.command + list(args),
                input=data,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            raise RetryObservation(
                f"Kubernetes {args[0]}: client deadline exceeded"
            ) from None
        if result.returncode:
            raise operation_error(result, args[0])
        return result.stdout

    def stats(self, host):
        """Read the fixed kubelet summary using nodes/stats, never nodes/proxy."""
        node = INVENTORY[host]
        credential = json.loads(
            self.run("config", "view", "--raw", "--minify", "-o", "json")
        )
        cluster = credential["clusters"][0]["cluster"]
        context = ssl.create_default_context(
            cadata=base64.b64decode(cluster["certificate-authority-data"]).decode()
        )
        token = credential["users"][0]["user"]["token"]
        request = urllib.request.Request(
            "https://" + node["talos"] + ":10250/stats/summary",
            headers={"Authorization": "Bearer " + token},
        )
        with urllib.request.urlopen(request, context=context, timeout=10) as response:
            body = response.read(8 * 1024 * 1024 + 1)
        if len(body) > 8 * 1024 * 1024:
            raise ValueError("Node statistics response exceeds limit")
        summary = json.loads(body)
        if summary["node"]["nodeName"] != node["node"]:
            raise ValueError("Node statistics identity mismatch")
        return summary

    def wait(self, *args):
        result = subprocess.run(
            self.command + list(args),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if result.returncode == 0:
            return True
        diagnostic = (result.stdout + result.stderr).lower()
        if "timed out waiting" in diagnostic or "timeout" in diagnostic:
            return False
        raise operation_error(result, "readiness")

    def get(self, resource, name=None, namespace=None):
        args = ["get", resource]
        if name:
            args.append(name)
        args += ["-n", namespace] if namespace else ["-A"]
        return json.loads(self.run(*args, "-o", "json"))

    def inventory(self):
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                key: executor.submit(self.get, resource)
                for key, resource in RESOURCES.items()
            }
            result = {}
            for key, future in futures.items():
                response = future.result()
                if not isinstance(response.get("items"), list) or response.get(
                    "metadata", {}
                ).get("continue"):
                    raise ValueError("Incomplete Kubernetes inventory: " + key)
                result[key] = response["items"]
        if time.monotonic() - started > 30:
            raise ValueError("Kubernetes inventory exceeded freshness deadline")
        return result

    def patch(self, resource, obj, operations, status=False):
        args = [
            "patch",
            resource,
            obj["metadata"]["name"],
            "--type=json",
            "-p",
            json.dumps(operations),
        ]
        if obj["metadata"].get("namespace"):
            args += ["-n", obj["metadata"]["namespace"]]
        if status:
            args += ["--subresource=status"]
        return self.run(*args)

    def guarded(self, resource, obj, operations, status=False):
        return self.patch(
            resource,
            obj,
            [
                {
                    "op": "test",
                    "path": "/metadata/uid",
                    "value": obj["metadata"]["uid"],
                },
                {
                    "op": "test",
                    "path": "/metadata/resourceVersion",
                    "value": obj["metadata"]["resourceVersion"],
                },
                *operations,
            ],
            status,
        )
