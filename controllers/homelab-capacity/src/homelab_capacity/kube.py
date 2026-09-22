"""Bounded kubectl adapter. Never print captured Kubernetes object bodies."""

import base64
import json
import ssl
import urllib.request
from .config import INVENTORY
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
