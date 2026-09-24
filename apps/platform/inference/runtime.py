"""Narrow Kubernetes adapter. Runtime Pods reserve quota once, requests do not."""

import json
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from store import backend_order

PREFIX = "homelab.tfdraw.dev/"


class Kubernetes:
    def __init__(self, namespace="homelab-inference"):
        self.namespace = namespace
        self.base = "https://kubernetes.default.svc"
        self.secret = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        self.tls = ssl.create_default_context(cafile=str(self.secret / "ca.crt"))

    def call(self, path, method="GET", body=None):
        req = urllib.request.Request(
            self.base + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": "Bearer "
                + (self.secret / "token").read_text().strip(),
                "Content-Type": "application/json-patch+json"
                if method == "PATCH"
                else "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, context=self.tls, timeout=5) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and method == "GET":
                return None
            raise

    @property
    def pods_path(self):
        return "/api/v1/namespaces/" + self.namespace + "/pods"


def ready(obj):
    return bool(obj) and any(
        c["type"] == "Ready" and c["status"] == "True"
        for c in obj.get("status", {}).get("conditions", [])
    )


def node_healthy(node):
    return (
        ready(node)
        and not node.get("spec", {}).get("unschedulable")
        and not any(
            c["type"] in {"MemoryPressure", "DiskPressure", "PIDPressure"}
            and c["status"] != "False"
            for c in node.get("status", {}).get("conditions", [])
        )
    )


def runtime_health(profile, node, pod, cilium):
    accepted = bool(node and profile.get("acceptedNodeUID") == node["metadata"]["uid"])
    network = any(
        x["spec"].get("nodeName") == profile["node"] and ready(x) for x in cilium
    )
    eligible = accepted and node_healthy(node) and network
    healthy = bool(
        profile.get("enabled")
        and eligible
        and ready(pod)
        and not pod["metadata"].get("deletionTimestamp")
    )
    if healthy and profile["kind"] == "gpu":
        healthy = (
            int(
                node.get("status", {}).get("allocatable", {}).get("nvidia.com/gpu", "0")
            )
            >= 1
        )
    address = pod.get("status", {}).get("podIP") if pod else None
    if healthy:
        if not address:
            return accepted, eligible, False
        try:
            with urllib.request.urlopen(
                "http://" + address + ":8080/health", timeout=2
            ) as response:
                healthy = response.status == 200
        except (OSError, ValueError):
            healthy = False
    return accepted, eligible, healthy


def runtime_pod(p, namespace):
    resources = dict(p["resources"])
    if p["kind"] == "gpu":
        resources["nvidia.com/gpu"] = "1"
    if p["kind"] == "cpu" and "nvidia.com/gpu" in resources:
        raise ValueError("CPU profiles cannot request a GPU")
    spec = {
        "restartPolicy": "Never",
        "automountServiceAccountToken": False,
        "nodeSelector": {"kubernetes.io/hostname": p["node"]},
        "tolerations": [
            {
                "key": PREFIX + "compute",
                "operator": "Equal",
                "value": "true",
                "effect": "NoSchedule",
            }
        ],
        "securityContext": {
            "runAsUser": 1000,
            "runAsGroup": 1000,
            "runAsNonRoot": True,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "containers": [
            {
                "name": "runtime",
                "image": p["image"],
                "imagePullPolicy": "IfNotPresent",
                "args": [
                    "--model",
                    "/models/" + p["modelFile"],
                    "--alias",
                    p["model"],
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "8080",
                    "--parallel",
                    "1",
                    "--ctx-size",
                    "4096",
                    "--n-gpu-layers",
                    "99" if p["kind"] == "gpu" else "0",
                    *p.get("args", []),
                ],
                "env": []
                if p["kind"] == "gpu"
                else [{"name": "NVIDIA_VISIBLE_DEVICES", "value": "void"}],
                "resources": {"requests": resources, "limits": resources},
                "securityContext": {
                    "allowPrivilegeEscalation": False,
                    "readOnlyRootFilesystem": True,
                    "capabilities": {"drop": ["ALL"]},
                },
                "readinessProbe": {
                    "httpGet": {"path": "/health", "port": 8080},
                    "periodSeconds": 5,
                },
                "volumeMounts": [
                    {"name": "models", "mountPath": "/models", "readOnly": True},
                    {"name": "scratch", "mountPath": "/tmp"},
                ],
            }
        ],
        "volumes": [
            {
                "name": "models",
                "hostPath": {"path": p["cachePath"] + "/models", "type": "Directory"},
            },
            {
                "name": "scratch",
                "emptyDir": {"sizeLimit": p["resources"]["ephemeral-storage"]},
            },
        ],
    }
    if not p.get("desktop"):
        # Talos cache belongs to this cluster workload, Ubuntu cache belongs to Ansible.
        spec["volumes"][0]["hostPath"]["type"] = "DirectoryOrCreate"
        spec["volumes"].append(
            {
                "name": "cache-code",
                "configMap": {
                    "name": "inference-code",
                    "items": [{"key": "cache.py", "path": "cache.py"}],
                },
            }
        )
        spec["initContainers"] = [
            {
                "name": "cache-model",
                "image": p["cacheImage"],
                "command": ["python", "-B", "/cache-code/cache.py"],
                "env": [
                    {"name": "MODEL_URL", "value": p["modelURL"]},
                    {"name": "MODEL_SHA256", "value": p["modelSHA256"]},
                    {"name": "MODEL_PATH", "value": "/models/" + p["modelFile"]},
                ],
                "securityContext": {
                    "runAsUser": 0,
                    "runAsNonRoot": False,
                    "allowPrivilegeEscalation": False,
                    "readOnlyRootFilesystem": True,
                    "capabilities": {"drop": ["ALL"]},
                },
                "resources": {
                    "requests": {"cpu": "100m", "memory": "64Mi"},
                    "limits": {"cpu": "500m", "memory": "128Mi"},
                },
                "volumeMounts": [
                    {"name": "models", "mountPath": "/models"},
                    {
                        "name": "cache-code",
                        "mountPath": "/cache-code",
                        "readOnly": True,
                    },
                ],
            }
        ]
    if p["kind"] == "gpu":
        spec["runtimeClassName"] = "nvidia"
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "inference-" + p["id"],
            "namespace": namespace,
            "labels": {
                "app": "inference-runtime",
                PREFIX + "backend": p["id"],
                "kueue.x-k8s.io/queue-name": p["queue"],
            },
        },
        "spec": spec,
    }


class Runtimes:
    def __init__(self, kube, config, store):
        self.kube, self.config, self.store = kube, config, store
        self.last_used = {}

    def reconcile(self):
        pending = self.store.pending()
        nodes = {
            p["node"]: self.kube.call("/api/v1/nodes/" + p["node"])
            for p in self.config["profiles"]
        }
        pods = self.kube.call(self.kube.pods_path)["items"]
        cilium = self.kube.call(
            "/api/v1/namespaces/kube-system/pods?labelSelector=k8s-app%3Dcilium"
        )["items"]
        result = []
        profiles = sorted(self.config["profiles"], key=backend_order)
        observed = {}
        for profile in profiles:
            pod = next(
                (
                    x
                    for x in pods
                    if x["metadata"]["name"] == "inference-" + profile["id"]
                ),
                None,
            )
            observed[profile["id"]] = runtime_health(
                profile, nodes[profile["node"]], pod, cilium
            )
        wanted = set()
        for request in pending:
            model = json.loads(request["payload"])["model"]
            candidates = [
                p
                for p in profiles
                if p.get("enabled")
                and p.get("acceptedNodeUID")
                and p["model"] == model
                and p["id"] not in wanted
                and not self.store.occupied(p["id"])
                and (
                    p["kind"] == "gpu"
                    and request["policy"] != "cpu-only"
                    or p["kind"] == "cpu"
                    and request["policy"] != "gpu-required"
                )
            ]
            # GPU-preferred only selects an immediately usable GPU slot.
            if request["policy"] == "gpu-preferred":
                candidates = [
                    p for p in candidates if p["kind"] != "gpu" or observed[p["id"]][2]
                ]
            candidates = [
                p
                for p in candidates
                if observed[p["id"]][0]
                and (not p.get("desktop") or observed[p["id"]][1])
            ]
            if candidates:
                wanted.add(candidates[0]["id"])
        for p in sorted(self.config["profiles"], key=backend_order):
            node = nodes[p["node"]]
            accepted, eligible, healthy = observed[p["id"]]
            if p.get("desktop") and accepted:
                taints = node.get("spec", {}).get("taints", [])
                other = [t for t in taints if t["key"] != PREFIX + "quarantine"]
                wanted_taints = (
                    other
                    if eligible
                    else other
                    + [
                        {
                            "key": PREFIX + "quarantine",
                            "value": "true",
                            "effect": "NoSchedule",
                        }
                    ]
                )
                if wanted_taints != taints:
                    self.kube.call(
                        "/api/v1/nodes/" + p["node"],
                        "PATCH",
                        [
                            {
                                "op": "test",
                                "path": "/metadata/uid",
                                "value": node["metadata"]["uid"],
                            },
                            {
                                "op": "test",
                                "path": "/metadata/resourceVersion",
                                "value": node["metadata"]["resourceVersion"],
                            },
                            {
                                "op": "add",
                                "path": "/spec/taints",
                                "value": wanted_taints,
                            },
                        ],
                    )
                    # Re-read next cycle, avoiding stale resourceVersion for shared profiles.
                    nodes[p["node"]] = self.kube.call("/api/v1/nodes/" + p["node"])
            pod = next(
                (x for x in pods if x["metadata"]["name"] == "inference-" + p["id"]),
                None,
            )
            if (
                pod
                and pod["metadata"].get("labels", {}).get(PREFIX + "backend") != p["id"]
            ):
                raise ValueError("Runtime name occupied by an unowned Pod")
            demand = p["id"] in wanted
            occupied = self.store.occupied(p["id"])
            now = time.monotonic()
            if demand or occupied:
                self.last_used[p["id"]] = now
            self.last_used.setdefault(p["id"], now)
            # GPU runtime is resident; CPU runtimes release their reservation after 5 minutes.
            desired = p.get("enabled", False) and (
                p["kind"] == "gpu"
                or demand
                or occupied
                or (pod and now - self.last_used[p["id"]] < 300)
            )
            # A server Pod may be queued while asleep. Existing Kueue checks alone wake it.
            # Desktop always stays quarantined until its acceptance receipt is installed.
            if desired and not pod and accepted:
                self.kube.call(
                    self.kube.pods_path, "POST", runtime_pod(p, self.kube.namespace)
                )
            if (
                pod
                and not occupied
                and (
                    not desired
                    or pod.get("status", {}).get("phase") in {"Succeeded", "Failed"}
                )
            ):
                self.kube.call(
                    self.kube.pods_path + "/" + pod["metadata"]["name"],
                    "DELETE",
                    {
                        "apiVersion": "v1",
                        "kind": "DeleteOptions",
                        "preconditions": {"uid": pod["metadata"]["uid"]},
                        "gracePeriodSeconds": 30,
                    },
                )
            address = pod.get("status", {}).get("podIP") if pod else None
            result.append(
                {
                    **p,
                    "healthy": bool(healthy),
                    "url": "http://" + address + ":8080" if address else None,
                    "nodeReady": bool(accepted and node_healthy(node)),
                    "terminated": bool(
                        pod
                        and pod.get("status", {}).get("containerStatuses")
                        and all(
                            c.get("state", {}).get("terminated", {}).get("finishedAt")
                            for c in pod["status"]["containerStatuses"]
                        )
                    ),
                    "generation": node["metadata"]["uid"]
                    + "/"
                    + node["status"]["nodeInfo"]["bootID"]
                    + "/"
                    + pod["metadata"]["uid"]
                    if node and pod
                    else None,
                }
            )
        return result
