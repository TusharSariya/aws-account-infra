from copy import deepcopy
from types import SimpleNamespace

import pytest

from homelab_capacity.config import INVENTORY
from homelab_capacity.coordinator import Coordinator
from homelab_capacity.journal import Journal
from homelab_capacity.platform import Platform


class Kube:
    def __init__(self, node):
        self.node = deepcopy(node)
        self.patches = []

    def get(self, resource, name, namespace=None):
        assert resource == "nodes"
        return deepcopy(self.node)

    def guarded(self, resource, obj, operations):
        self.patches.extend(operations)
        for op in operations:
            if op["path"] == "/spec/unschedulable":
                self.node["spec"]["unschedulable"] = op["value"]
            elif op["op"] == "remove":
                self.node["metadata"]["annotations"].pop(
                    "homelab.tfdraw.dev/power-operation"
                )


def setup(tmp_path):
    registered = INVENTORY["secondary"]
    node = {
        "metadata": {
            "name": registered["node"],
            "uid": registered["node_uid"],
            "annotations": {"homelab.tfdraw.dev/power-operation": "operation"},
        },
        "spec": {"unschedulable": True},
        "status": {
            "nodeInfo": {"systemUUID": registered["system_uuid"]},
            "conditions": [{"type": "Ready", "status": "True"}],
        },
    }
    journal = Journal(tmp_path)
    record = {
        "id": "operation",
        "phase": "quiesced",
        "node": node,
        "storage": {},
        "volume": {},
        "objects": [],
    }
    journal.write("secondary-platform.json", record)
    kube = Kube(node)
    management = SimpleNamespace(
        storage=lambda host: {},
        power=lambda host: SimpleNamespace(
            get_power=lambda: SimpleNamespace(power="on")
        ),
        pve=lambda host: {"status": "running", "other_running": [], "users": []},
    )
    objects = {
        name: []
        for name in [
            "pods",
            "replicasets",
            "jobs",
            "workloads",
            "backups",
            "applications",
            "deployments",
            "leases",
            "pv",
            "pvc",
        ]
    }
    objects["nodes"] = [kube.node]
    return kube, management, journal, objects


def test_restore_finishes_and_clears_only_its_own_cordon(tmp_path):
    kube, management, journal, objects = setup(tmp_path)
    Platform(kube, management, journal).restore("secondary", objects)
    assert journal.read("secondary-platform.json")["phase"] == "complete"
    assert not kube.node["spec"]["unschedulable"]
    assert not kube.node["metadata"]["annotations"]


def test_restore_preserves_unrelated_operator_cordon(tmp_path):
    kube, management, journal, objects = setup(tmp_path)
    kube.node["metadata"]["annotations"].clear()
    with pytest.raises(RuntimeError, match="unrelated operator cordon"):
        Platform(kube, management, journal).restore("secondary", objects)
    assert not kube.patches


def test_unfinished_restore_is_not_admission_ready(tmp_path):
    kube, management, journal, objects = setup(tmp_path)
    kube.node["spec"]["unschedulable"] = False
    objects["pods"] = [
        {
            "metadata": {
                "namespace": "kube-system",
                "name": name,
                "ownerReferences": [
                    {"kind": "DaemonSet", "name": name, "controller": True}
                ],
            },
            "spec": {"nodeName": INVENTORY["secondary"]["node"]},
            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
        }
        for name in ["cilium", "kube-proxy"]
    ]
    controller = Coordinator({}, kube=kube, management=management, journal=journal)
    assert not controller.observation("secondary", objects).ready
    record = journal.read("secondary-platform.json")
    record["phase"] = "complete"
    journal.write("secondary-platform.json", record)
    assert controller.observation("secondary", objects).ready


@pytest.mark.parametrize("node", ["talos-worker-01", "talos-worker-02", None])
def test_recovery_checks_host_storage_without_capturing_other_hosts_tests(
    tmp_path, node
):
    kube, management, journal, objects = setup(tmp_path)
    record = journal.read("secondary-platform.json")
    pv = {"uid": "test-volume", "hostPath": {"path": "/local/test"}, "nodeAffinity": {}}
    if node:
        pv["nodeAffinity"] = {
            "required": {
                "nodeSelectorTerms": [
                    {
                        "matchExpressions": [
                            {
                                "key": "kubernetes.io/hostname",
                                "operator": "In",
                                "values": [node],
                            }
                        ]
                    }
                ]
            }
        }
    record["storage"] = {
        "pv//test-volume": pv,
        "pvc/test/claim": {
            "uid": "test-claim",
            "volumeName": "test-volume",
            "storageClassName": "local",
        },
    }
    journal.write("secondary-platform.json", record)
    if node == "talos-worker-01":
        Platform(kube, management, journal).restore("secondary", objects)
        assert journal.read("secondary-platform.json")["phase"] == "complete"
        assert journal.read("secondary-platform.json")["storage"] == record["storage"]
    else:
        with pytest.raises(RuntimeError, match="Protected storage"):
            Platform(kube, management, journal).restore("secondary", objects)
        assert not kube.patches


def test_recovery_ignores_unbound_claims_but_keeps_bound_ones(tmp_path):
    kube, management, journal, objects = setup(tmp_path)
    record = journal.read("secondary-platform.json")
    record["storage"] = {
        "pvc/storage-check-abc/delete": {
            "uid": "gone-fixture",
            "volumeName": None,
            "storageClassName": "worker-local-delete",
        }
    }
    journal.write("secondary-platform.json", record)
    Platform(kube, management, journal).restore("secondary", objects)
    assert journal.read("secondary-platform.json")["phase"] == "complete"
    record["phase"] = "quiesced"
    record["storage"]["pvc/data/claim"] = {
        "uid": "bound",
        "volumeName": "missing-volume",
        "storageClassName": "local",
    }
    journal.write("secondary-platform.json", record)
    with pytest.raises(RuntimeError, match="Protected storage"):
        Platform(kube, management, journal).restore("secondary", objects)

