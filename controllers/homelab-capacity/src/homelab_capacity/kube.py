"""Bounded kubectl adapter. Never print captured Kubernetes object bodies."""

import json
import subprocess
from pathlib import Path

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
    "cronjobs": "cronjobs",
    "clusters": "clusters.postgresql.cnpg.io",
    "pv": "pv",
    "pvc": "pvc",
    "leases": "leases.coordination.k8s.io",
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
        result = subprocess.run(
            self.command + list(args),
            input=data,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        if result.returncode:
            raise RuntimeError("Kubernetes operation failed: " + args[0])
        return result.stdout

    def wait(self, *args):
        result = subprocess.run(
            self.command + list(args),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        if result.returncode == 0:
            return True
        diagnostic = (result.stdout + result.stderr).lower()
        if "timed out waiting" in diagnostic or "timeout" in diagnostic:
            return False
        raise RuntimeError("Kubernetes readiness check failed")

    def get(self, resource, name=None, namespace=None):
        args = ["get", resource]
        if name:
            args.append(name)
        args += ["-n", namespace] if namespace else ["-A"]
        return json.loads(self.run(*args, "-o", "json"))

    def inventory(self):
        return {key: self.get(resource)["items"] for key, resource in RESOURCES.items()}

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
