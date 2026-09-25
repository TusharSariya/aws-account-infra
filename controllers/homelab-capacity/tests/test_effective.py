from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from homelab_capacity.effective import commitments, effective
from homelab_capacity.kueue import (
    admission_budget,
    admission_patch,
    unreserved_demand,
)

G = 1024**3


def fixture():
    now = datetime.now(timezone.utc)
    node = {
        "metadata": {"name": "talos-worker-01"},
        "status": {
            "conditions": [{"type": "Ready", "status": "True"}],
            "allocatable": {
                "cpu": "38",
                "memory": "110Gi",
                "ephemeral-storage": "300Gi",
                "pods": "110",
            },
        },
    }
    fs = {"time": now.isoformat(), "usedBytes": 20 * G, "availableBytes": 280 * G}
    summary = {
        "node": {
            "nodeName": "talos-worker-01",
            "fs": fs,
            "runtime": {"imageFs": deepcopy(fs)},
        },
        "pods": [],
    }
    objects = {
        k: []
        for k in [
            "pods",
            "deployments",
            "statefulsets",
            "daemonsets",
            "clusters",
            "workloads",
            "nodes",
        ]
    }
    objects["nodes"] = [node]
    return node, objects, summary


def pod(name, cpu="2", memory="4Gi", scratch="10Gi", queued=False):
    return {
        "metadata": {
            "uid": name,
            "name": name,
            "namespace": "svc",
            "labels": {
                "app": name,
                **({"kueue.x-k8s.io/queue-name": "ci"} if queued else {}),
            },
        },
        "spec": {
            "nodeName": "talos-worker-01",
            "containers": [
                {
                    "resources": {
                        "requests": {
                            "cpu": cpu,
                            "memory": memory,
                            "ephemeral-storage": scratch,
                        }
                    }
                }
            ],
        },
    }


def test_capacity_tracks_actual_commitments_and_not_instant_cpu_use():
    node, objects, summary = fixture()
    objects["pods"] = [pod("platform"), pod("compute", queued=True)]
    objects["workloads"] = [
        {
            "metadata": {"ownerReferences": [{"uid": "compute"}]},
            "status": {"admission": {"clusterQueue": "homelab-compute"}},
        }
    ]
    result = effective(node, objects, summary)["quotas"]
    assert result == {
        "cpu": "36.000",
        "memory": str(106 * G),
        "pods": "109",
        "ephemeral-storage": str(270 * G),
    }
    objects["pods"][0]["spec"]["containers"][0]["resources"]["requests"]["cpu"] = "4"
    assert effective(node, objects, summary)["quotas"]["cpu"] == "34.000"


def test_scaled_down_templates_init_sidecars_and_overhead_are_reserved():
    node, objects, summary = fixture()
    template = pod("service")
    template["spec"].pop("nodeName")
    template["spec"]["overhead"] = {"cpu": "250m"}
    template["spec"]["initContainers"] = [
        {"restartPolicy": "Always", "resources": {"requests": {"cpu": "1"}}},
        {"resources": {"requests": {"cpu": "8"}}},
    ]
    controller = {
        "metadata": {"uid": "d", "name": "service", "namespace": "svc"},
        "spec": {"replicas": 0, "template": template},
    }
    objects["deployments"] = [controller]
    saved = deepcopy(controller)
    saved["spec"]["replicas"] = 2
    record = {
        "phase": "quiesced",
        "objects": [{"resource": "deployments", "object": saved}],
    }
    assert commitments(node, objects, record)["cpu"] == 18.5
    assert effective(node, objects, summary, record)["quotas"]["pods"] == "108"


def test_storage_reclaims_without_double_counting_shared_filesystems():
    node, objects, summary = fixture()
    objects["pods"] = [pod("compute", queued=True)]
    objects["workloads"] = [
        {
            "metadata": {"ownerReferences": [{"uid": "compute"}]},
            "status": {"admission": {"clusterQueue": "homelab-compute"}},
        }
    ]
    summary["pods"] = [
        {"podRef": {"uid": "compute"}, "ephemeral-storage": {"usedBytes": 5 * G}}
    ]
    assert effective(node, objects, summary)["quotas"]["ephemeral-storage"] == str(
        285 * G
    )
    summary["node"]["fs"]["availableBytes"] = 0
    assert effective(node, objects, summary)["quotas"]["ephemeral-storage"] == str(
        5 * G
    )
    summary["node"]["fs"]["availableBytes"] = 280 * G
    assert effective(node, objects, summary)["quotas"]["ephemeral-storage"] == str(
        285 * G
    )


def test_stale_storage_and_wrong_node_fail_closed():
    node, objects, summary = fixture()
    summary["node"]["fs"]["time"] = (
        datetime.now(timezone.utc) - timedelta(seconds=31)
    ).isoformat()
    with pytest.raises(ValueError, match="Fresh"):
        effective(node, objects, summary)
    summary["node"]["nodeName"] = "other"
    with pytest.raises(ValueError, match="identity"):
        effective(node, objects, summary)


def workload(name, cpu="2", admitted=False):
    return {
        "metadata": {
            "uid": name,
            "name": name,
            "namespace": "homelab-jobs",
            "resourceVersion": "1",
        },
        "spec": {"queueName": "argo"},
        "status": {
            "admission": {
                "clusterQueue": "homelab-compute",
                "podSetAssignments": [
                    {
                        "count": 1,
                        "flavors": {
                            r: "homelab-worker"
                            for r in ["cpu", "memory", "ephemeral-storage", "pods"]
                        },
                        "resourceUsage": {
                            "cpu": cpu,
                            "memory": "1Gi",
                            "ephemeral-storage": "1Gi",
                            "pods": "1",
                        },
                    }
                ],
            },
            "admissionChecks": [{"name": "homelab-host-ready", "state": "Pending"}],
            "conditions": [{"type": "Admitted", "status": "True"}] if admitted else [],
        },
    }


@pytest.mark.parametrize(
    "resource,value",
    [("cpu", "0"), ("memory", "0"), ("ephemeral-storage", "0"), ("pods", "0")],
)
def test_each_exhausted_resource_stops_new_work_but_preserves_running(resource, value):
    budget = {"cpu": "10", "memory": "10Gi", "ephemeral-storage": "10Gi", "pods": "10"}
    budget[resource] = value
    running = workload("running", admitted=True)
    assert (
        admission_budget([running, workload("new")], {"primary": budget}, {"primary"})
        == set()
    )
    assert admission_patch(running, set()) is None


def test_small_job_bypasses_large_and_cancellation_releases_capacity():
    budget = {
        "primary": {
            "cpu": "4",
            "memory": "10Gi",
            "ephemeral-storage": "10Gi",
            "pods": "10",
        }
    }
    big, small = workload("a-big", "5"), workload("b-small", "1")
    assert admission_budget([big, small], budget, {"primary"}) == {"b-small"}
    running = workload("running", "4", True)
    assert not admission_budget([running, small], budget, {"primary"})
    running["metadata"]["deletionTimestamp"] = "now"
    assert not admission_budget([running, small], budget, {"primary"})
    running["status"]["conditions"].append({"type": "Finished", "status": "True"})
    assert admission_budget([running, small], budget, {"primary"}) == {"b-small"}


def test_unreserved_work_wakes_primary_then_secondary_when_primary_full():
    node, objects, _ = fixture()
    secondary = deepcopy(node)
    secondary["metadata"]["name"] = "talos-worker-02"
    objects["nodes"].append(secondary)
    w = workload("new")
    w.pop("status")
    template = pod("new")
    template["spec"].pop("nodeName")
    w["spec"]["podSets"] = [{"count": 1, "template": template}]
    objects["workloads"] = [w]
    assert unreserved_demand(objects, {}) == {"primary"}
    quotas = {"cpu": "8", "memory": "8Gi", "ephemeral-storage": "20Gi", "pods": "10"}
    assert unreserved_demand(
        objects, {"primary": dict(quotas, cpu="0"), "secondary": quotas}
    ) == {"secondary"}
    template["spec"]["nodeSelector"] = {"kubernetes.io/hostname": "talos-worker-01"}
    assert unreserved_demand(
        objects, {"primary": dict(quotas, cpu="0"), "secondary": quotas}
    ) == {"primary"}
    w["spec"]["queueName"] = "desktop-gpu"
    assert unreserved_demand(objects, {}) == set()


def test_orphaned_terminating_compute_remains_committed_until_stopped():
    node, objects, summary = fixture()
    running = pod("orphan", cpu="38", queued=True)
    running["metadata"]["deletionTimestamp"] = "now"
    objects["pods"] = [running]
    assert effective(node, objects, summary)["quotas"]["cpu"] == "0.000"
    running["status"] = {"phase": "Succeeded"}
    assert effective(node, objects, summary)["quotas"]["cpu"] == "38.000"
