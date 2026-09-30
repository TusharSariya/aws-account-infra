"""Crash a real coordinator after a partial API mutation and reload its journal."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from homelab_capacity.config import INVENTORY
from homelab_capacity.coordinator import Coordinator
from homelab_capacity.journal import Journal
from homelab_capacity.kube import RESOURCES
from homelab_capacity.kueue import CONTROLLER
from homelab_capacity.lifecycle import State


class Api:
    def __init__(self, node, deployments, cronjob):
        self.objects = {key: [] for key in RESOURCES}
        self.objects["nodes"] = [node]
        self.objects["deployments"] = deployments
        self.objects["cronjobs"] = [cronjob]
        self.crash = True
        self.writes = 0

    def inventory(self):
        return deepcopy(self.objects)

    def get(self, resource, name=None, namespace=None):
        if resource == "admissionchecks.kueue.x-k8s.io":
            return {
                "spec": {"controllerName": CONTROLLER},
                "status": {"conditions": [{"type": "Active", "status": "True"}]},
            }
        return deepcopy(
            next(o for o in self.objects[resource] if o["metadata"]["name"] == name)
        )

    def guarded(self, resource, before, operations, **kwargs):
        current = next(
            o
            for o in self.objects[resource]
            if o["metadata"]["name"] == before["metadata"]["name"]
        )
        assert current["metadata"]["uid"] == before["metadata"]["uid"]
        assert (
            current["metadata"]["resourceVersion"]
            == before["metadata"]["resourceVersion"]
        )
        for operation in operations:
            path = operation["path"].strip("/").split("/")
            target = current
            for key in path[:-1]:
                target = target[key]
            key = path[-1].replace("~1", "/").replace("~0", "~")
            if operation["op"] == "remove":
                target.pop(key)
            else:
                target[key] = deepcopy(operation["value"])
        current["metadata"]["resourceVersion"] = str(
            int(current["metadata"]["resourceVersion"]) + 1
        )
        self.writes += 1
        if resource == "deployments":
            # API updates happen before the client sees an acknowledgement.
            replicas = current["spec"]["replicas"]
            current["status"] = {
                "observedGeneration": 1,
                "readyReplicas": replicas,
                "updatedReplicas": replicas,
            }
            if self.crash:
                self.crash = False
                raise SystemExit("Simulated process loss after accepted scale")


def setup(tmp_path):
    def meta(name, namespace=None):
        return {
            "name": name,
            "uid": name,
            "resourceVersion": "1",
            "generation": 1,
            **({"namespace": namespace} if namespace else {}),
        }

    node = {
        "metadata": meta(INVENTORY["primary"]["node"]),
        "spec": {"unschedulable": True},
        "status": {
            "nodeInfo": {"systemUUID": INVENTORY["primary"]["system_uuid"]},
            "conditions": [{"type": "Ready", "status": "True"}],
        },
    }
    node["metadata"]["uid"] = INVENTORY["primary"]["node_uid"]
    node["metadata"]["annotations"] = {
        "homelab.tfdraw.dev/power-operation": "operation",
        "homelab.tfdraw.dev/power-intent": "sleep",
    }
    deployments = [
        {"metadata": meta(name, "homelab-cache"), "spec": {"replicas": 1}}
        for name in ["local-path-provisioner", "nexus"]
    ]
    cronjob = {
        "metadata": meta("cache-monitor", "homelab-cache"),
        "spec": {"suspend": False},
    }
    record = {
        "id": "operation",
        "phase": "quiesced",
        "node": deepcopy(node),
        "storage": {},
        "volume": {"uuid": "retained"},
        "objects": [
            {"resource": "deployments", "object": deepcopy(d)} for d in deployments
        ],
        "cronjobs": [deepcopy(cronjob)],
    }
    for d in deployments:
        d["spec"]["replicas"] = 0
    cronjob["spec"]["suspend"] = True
    api = Api(node, deployments, cronjob)
    journal = Journal(tmp_path)
    journal.write("primary-platform.json", record)
    journal.write("primary.json", State(phase="restoring").to_dict())
    management = SimpleNamespace(
        power=lambda host: SimpleNamespace(
            get_power=lambda: SimpleNamespace(power="on")
        ),
        pve=lambda host: {"status": "running", "other_running": [], "users": False},
        storage=lambda host: {"uuid": "retained"},
    )
    config = {"modes": {"primary": "automatic", "secondary": "observe"}}
    return config, api, management, journal, record


def test_reload_completes_partial_restore_and_preserves_snapshot(tmp_path):
    config, api, management, journal, record = setup(tmp_path)
    controller = Coordinator(config, kube=api, management=management, journal=journal)
    with pytest.raises(SystemExit):
        controller.tick()
    assert journal.read("primary.json")["pending"] == "restore"
    assert [d["spec"]["replicas"] for d in api.objects["deployments"]] == [1, 0]
    controller = Coordinator(config, kube=api, management=management, journal=journal)
    for _ in range(5):
        controller.tick()
        if journal.read("primary-platform.json")["phase"] == "complete":
            break
    restored = journal.read("primary-platform.json")
    assert restored["phase"] == "complete"
    assert restored["objects"] == record["objects"]
    assert restored["storage"] == record["storage"]
    assert all(d["spec"]["replicas"] == 1 for d in api.objects["deployments"])
    assert api.objects["cronjobs"][0]["spec"]["suspend"] is False
    assert not api.objects["nodes"][0]["spec"]["unschedulable"]
    assert api.objects["nodes"][0]["metadata"]["annotations"] == {}


@pytest.mark.parametrize("fault", ["storage", "cordon"])
def test_restart_does_not_mutate_after_storage_or_ownership_changes(tmp_path, fault):
    config, api, management, journal, _ = setup(tmp_path)
    with pytest.raises(SystemExit):
        Coordinator(config, kube=api, management=management, journal=journal).tick()
    if fault == "storage":
        management.storage = lambda host: {"uuid": "replacement"}
    else:
        node = api.objects["nodes"][0]
        node["spec"]["unschedulable"] = True
        node["metadata"]["annotations"]["homelab.tfdraw.dev/power-operation"] = (
            "operator"
        )
    before = deepcopy(api.objects)
    controller = Coordinator(config, kube=api, management=management, journal=journal)
    controller.tick()
    assert controller.states["primary"].phase == "blocked"
    assert api.objects["deployments"] == before["deployments"]
    assert api.objects["cronjobs"] == before["cronjobs"]
    assert api.objects["nodes"][0]["spec"] == before["nodes"][0]["spec"]
    assert (
        api.objects["nodes"][0]["metadata"]["annotations"][
            "homelab.tfdraw.dev/power-operation"
        ]
        == before["nodes"][0]["metadata"]["annotations"][
            "homelab.tfdraw.dev/power-operation"
        ]
    )
    assert journal.read("primary-platform.json")["phase"] == "quiesced"


def test_inventory_outage_cannot_hide_expired_shutdown(tmp_path):
    config, api, management, journal, _ = setup(tmp_path)
    controller = Coordinator(config, kube=api, management=management, journal=journal)
    controller.states["primary"] = State(
        phase="stopping", pending="await-off", deadline=0
    )

    def unavailable():
        raise RuntimeError("Inventory unavailable")

    api.inventory = unavailable
    with pytest.raises(RuntimeError, match="Inventory unavailable"):
        controller.tick()
    assert journal.read("primary.json")["phase"] == "blocked"
    assert api.writes == 0
