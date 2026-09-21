"""Render the one application from a reviewed, immutable image selection."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def render(selection):
    image = selection.get("image") or ""
    if not re.fullmatch(
        r"ghcr\.io/tusharsariyaorg/pilot-http@sha256:[a-f0-9]{64}", image
    ):
        raise ValueError("Record the built GHCR digest in image.json before rendering")
    labels = {"app": "pilot-http", "monitoring.homelab/pilot-logs": "true"}
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": "pilot-http",
            "namespace": "pilot-app",
            "annotations": {"argocd.argoproj.io/sync-options": "Prune=false"},
        },
        "spec": {
            "replicas": 1,
            "revisionHistoryLimit": 2,
            "selector": {"matchLabels": {"app": "pilot-http"}},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "automountServiceAccountToken": False,
                    "nodeSelector": {"prototype.homelab/pool": "workers"},
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 65534,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "http",
                            "image": image,
                            "ports": [{"containerPort": 8080}],
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "resources": {
                                "requests": {"cpu": "10m", "memory": "16Mi"},
                                "limits": {"cpu": "100m", "memory": "32Mi"},
                            },
                            "readinessProbe": {
                                "httpGet": {"path": "/healthz", "port": 8080}
                            },
                            "livenessProbe": {
                                "httpGet": {"path": "/healthz", "port": 8080}
                            },
                        }
                    ],
                },
            },
        },
    }
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": "pilot-http",
            "namespace": "pilot-app",
            "annotations": {"argocd.argoproj.io/sync-options": "Prune=false"},
        },
        "spec": {
            "selector": {"app": "pilot-http"},
            "ports": [{"port": 8080, "targetPort": 8080}],
        },
    }
    return {"apiVersion": "v1", "kind": "List", "items": [deployment, service]}


if __name__ == "__main__":
    result = render(json.loads((ROOT / "image.json").read_text()))
    (ROOT / "manifests").mkdir(exist_ok=True)
    (ROOT / "manifests/app.json").write_text(json.dumps(result, indent=2) + "\n")
