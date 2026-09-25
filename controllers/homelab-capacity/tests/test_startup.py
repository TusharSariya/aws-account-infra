"""Restoration launches independent chains and incomplete inventories fail closed."""

from threading import Barrier, Lock

import pytest
from homelab_capacity.coordinator import Coordinator
from homelab_capacity.kube import RESOURCES, Kube
from homelab_capacity.platform import Platform
from test_restoration import setup


def test_inventory_is_bounded_and_concurrent():
    kube = Kube({"kubectl": "kubectl", "kubeconfig": "unused"})
    barrier = Barrier(4)
    lock = Lock()
    active = 0
    maximum = 0
    calls = 0

    def get(resource):
        nonlocal active, maximum, calls
        with lock:
            active += 1
            maximum = max(maximum, active)
            calls += 1
            order = calls
        if order <= 4:
            barrier.wait(timeout=5)
        with lock:
            active -= 1
        return {"items": [resource]}

    kube.get = get
    objects = kube.inventory()
    assert set(objects) == set(RESOURCES)
    assert 2 <= maximum <= 4


@pytest.mark.parametrize(
    "response", [{}, {"items": [], "metadata": {"continue": "more"}}, {"items": None}]
)
def test_incomplete_inventory_never_returns_partial_snapshot(response):
    kube = Kube({"kubectl": "kubectl", "kubeconfig": "unused"})
    kube.get = lambda resource: response if resource == "pods" else {"items": []}
    with pytest.raises(ValueError, match="Incomplete"):
        kube.inventory()


def test_independent_restoration_progresses_while_cache_database_waits(tmp_path):
    kube, management, journal, objects = setup(tmp_path)
    record = journal.read("secondary-platform.json")
    names = [
        "local-path-provisioner",
        "cnpg",
        "nexus-postgres",
        "nexus",
        "prometheus",
        "argocd-redis",
        "argocd-server",
        "argocd-repo-server",
    ]
    record["objects"] = [
        {"resource": "deployments", "object": {"metadata": {"name": n}}} for n in names
    ]
    journal.write("secondary-platform.json", record)
    platform = Platform(kube, management, journal)
    started = []
    ready = {"local-path-provisioner", "cnpg", "argocd-redis", "argocd-repo-server"}

    def scale(entry, restoring, *, wait):
        assert restoring and not wait
        name = entry["object"]["metadata"]["name"]
        started.append(name)
        return name in ready

    platform.scale = scale
    platform.restore("secondary", objects)
    assert {"cnpg", "nexus-postgres", "prometheus", "argocd-server"} <= set(started)
    assert "nexus" not in started
    assert journal.read("secondary-platform.json")["phase"] != "complete"
    # Resume from the durable journal, with no ordering based on prior memory.
    ready.update(names)
    started.clear()
    platform = Platform(kube, management, journal)
    platform.scale = scale
    platform.restore("secondary", objects)
    assert "nexus" in started
    assert journal.read("secondary-platform.json")["phase"] == "complete"


def test_active_polling_and_first_observation_timestamps(tmp_path):
    kube, management, journal, _ = setup(tmp_path)
    coordinator = Coordinator({}, kube=kube, management=management, journal=journal)
    for state in coordinator.states.values():
        state.phase = "idle"
    assert coordinator.poll_interval() == 15
    coordinator.states["primary"].phase = "waking"
    assert coordinator.poll_interval() == 5
    coordinator.milestone("primary", "power_on_request", reset=True)
    first = journal.read("primary-startup.json")
    coordinator.milestone("primary", "power_on_request")
    assert journal.read("primary-startup.json") == first
