import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
from runtime import Runtimes, runtime_pod
from store import Store


def profile(name, kind="cpu", desktop=False, priority=1):
    return dict(
        id=name,
        kind=kind,
        desktop=desktop,
        priority=priority,
        model="qwen",
        enabled=True,
        node=name,
        acceptedNodeUID=name,
        queue="desktop" if desktop else "server-cpu",
        image="test@sha256:" + "a" * 64,
        cacheImage="test@sha256:" + "a" * 64,
        modelURL="https://example.com/model.gguf",
        modelSHA256="a" * 64,
        modelFile="qwen.gguf",
        cachePath="/cache",
        resources={"cpu": "2", "memory": "2Gi", "ephemeral-storage": "1Gi"},
    )


def node(name, ready=True):
    return {
        "metadata": {"name": name, "uid": name, "resourceVersion": "1"},
        "spec": {},
        "status": {
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
            "nodeInfo": {"bootID": "boot"},
            "allocatable": {"nvidia.com/gpu": "1"},
        },
    }


class Kube:
    namespace = "homelab-inference"
    pods_path = "/api/v1/namespaces/homelab-inference/pods"

    def __init__(self, profiles, offline=()):
        self.nodes = {
            p["node"]: node(p["node"], p["node"] not in offline) for p in profiles
        }
        self.pods = []
        self.created = []
        self.deleted = []

    def call(self, path, method="GET", body=None):
        if method == "POST":
            self.created.append(body)
            return body
        if method == "DELETE":
            self.deleted.append(body)
            return {}
        if method == "PATCH":
            return {}
        if path.startswith("/api/v1/nodes/"):
            return self.nodes[path.split("/")[-1]]
        if "kube-system" in path:
            return {
                "items": [
                    {
                        "spec": {"nodeName": name},
                        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
                    }
                    for name in self.nodes
                ]
            }
        return {"items": self.pods}


def test_gpu_waiting_never_creates_cpu_wake_demand(tmp_path):
    ps = [
        profile("gpu", "gpu", True, 0),
        profile("desktop", "cpu", True, 1),
        profile("server", "cpu", False, 2),
    ]
    store = Store(tmp_path / "db")
    store.submit({"model": "qwen"}, policy="gpu-required")
    kube = Kube(ps, offline=["gpu", "desktop", "server"])
    Runtimes(kube, {"profiles": ps}, store).reconcile()
    assert [p["metadata"]["name"] for p in kube.created] == ["inference-gpu"]


def test_cpu_prefers_ready_desktop_and_only_then_wakes_server(tmp_path):
    ps = [profile("desktop", "cpu", True, 1), profile("server", "cpu", False, 2)]
    store = Store(tmp_path / "db")
    store.submit({"model": "qwen"}, policy="cpu-only")
    kube = Kube(ps, offline=["server"])
    Runtimes(kube, {"profiles": ps}, store).reconcile()
    assert [p["metadata"]["name"] for p in kube.created] == ["inference-desktop"]
    kube = Kube(ps, offline=["desktop", "server"])
    Runtimes(kube, {"profiles": ps}, store).reconcile()
    assert [p["metadata"]["name"] for p in kube.created] == ["inference-server"]


def test_cpu_has_no_gpu_access_and_resources_are_reserved_once():
    pod = runtime_pod(profile("cpu"), "homelab-inference")
    assert "runtimeClassName" not in pod["spec"]
    c = pod["spec"]["containers"][0]
    assert "nvidia.com/gpu" not in c["resources"]["requests"]
    assert c["env"] == [{"name": "NVIDIA_VISIBLE_DEVICES", "value": "void"}]
    assert pod["metadata"]["labels"]["kueue.x-k8s.io/queue-name"] == "server-cpu"


def test_idle_cpu_releases_reservation_but_uncertain_execution_does_not(tmp_path):
    p = profile("cpu")
    store = Store(tmp_path / "db")
    kube = Kube([p])
    pod = runtime_pod(p, kube.namespace)
    pod["metadata"]["uid"] = "pod"
    kube.pods = [pod]
    runtimes = Runtimes(kube, {"profiles": [p]}, store)
    runtimes.last_used["cpu"] = 0
    with patch("runtime.time.monotonic", return_value=301):
        runtimes.reconcile()
    assert len(kube.deleted) == 1
    r = store.submit({"model": "qwen"}, policy="cpu-only")
    store.claim([{**p, "healthy": True, "generation": "node/boot/pod"}])
    store.recover()
    kube.deleted = []
    with patch("runtime.time.monotonic", return_value=999):
        runtimes.reconcile()
    assert kube.deleted == []
    assert store.get(r["id"])["state"] == "uncertain"


def test_node_uid_replacement_cannot_inherit_acceptance(tmp_path):
    p = profile("cpu")
    store = Store(tmp_path / "db")
    store.submit({"model": "qwen"})
    kube = Kube([p])
    kube.nodes["cpu"]["metadata"]["uid"] = "replacement"
    profiles = Runtimes(kube, {"profiles": [p]}, store).reconcile()
    assert not profiles[0]["healthy"]
    assert not kube.created
