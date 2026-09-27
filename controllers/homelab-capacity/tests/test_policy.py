from homelab_capacity.policy import classify, housekeeping_jobs


def inventory():
    return {
        k: []
        for k in ["pods", "replicasets", "jobs", "workloads", "backups", "applications"]
    }


def test_unknown_standalone_pod_blocks_retirement():
    data = inventory()
    data["pods"] = [
        {
            "metadata": {"namespace": "test", "name": "survivor"},
            "spec": {"nodeName": "talos-worker-01"},
        }
    ]
    demand, blockers = classify("primary", data)
    assert not demand and blockers == ["Active or unregistered pod: test/survivor"]


def test_missing_inventory_is_not_idle():
    assert classify("primary", {})[1] == ["Incomplete Kubernetes inventory"]


def test_backup_schedule_wakes_but_housekeeping_does_not():
    data = inventory()
    job = {
        "metadata": {
            "namespace": "homelab-data",
            "name": "backup",
            "ownerReferences": [
                {"kind": "CronJob", "name": "apps-db-backup", "controller": True}
            ],
        }
    }
    data["jobs"] = [job]
    assert classify("primary", data)[0]
    job["metadata"]["ownerReferences"][0]["name"] = "apps-db-backup-monitor"
    assert classify("primary", data) == (False, [])
    job["status"] = {"active": 1}
    assert classify("primary", data) == (False, [])
    assert housekeeping_jobs(data)


def test_idle_ai_workload_matches_live_pod_uid_without_template_labels():
    data = inventory()
    data["pods"] = [
        {
            "metadata": {
                "namespace": "homelab-models",
                "name": "ai-1",
                "uid": "pod-uid",
                "labels": {"app": "ai-runtime", "kueue.x-k8s.io/queue-name": "ai"},
            },
            "spec": {},
        }
    ]
    workload = {
        "metadata": {
            "namespace": "homelab-models",
            "name": "workload",
            "ownerReferences": [
                {"kind": "Pod", "name": "ai-1", "uid": "pod-uid", "controller": True}
            ],
        },
        "spec": {"podSets": [{"template": {"metadata": {}}}]},
        "status": {
            "admission": {
                "clusterQueue": "homelab-compute",
                "podSetAssignments": [{"flavors": {"cpu": "homelab-worker"}}],
            }
        },
    }
    data["workloads"] = [workload]
    assert classify("primary", data, verified_ai_idle=True) == (False, [])
    assert classify("primary", data, verified_ai_idle=False)[0]
    workload["metadata"]["ownerReferences"][0]["uid"] = "stale-pod"
    assert classify("primary", data, verified_ai_idle=True)[0]


def test_housekeeping_pods_are_matched_by_job_identity_and_gate_retirement():
    data = inventory()
    data["jobs"] = [
        {
            "metadata": {
                "namespace": "homelab-cache",
                "name": "monitor",
                "uid": "job-uid",
                "ownerReferences": [
                    {"kind": "CronJob", "name": "cache-monitor", "controller": True}
                ],
            },
            "status": {"active": 1},
        }
    ]
    pod = {
        "metadata": {
            "namespace": "homelab-cache",
            "name": "monitor-pod",
            "ownerReferences": [
                {"kind": "Job", "name": "monitor", "uid": "job-uid", "controller": True}
            ],
        },
        "spec": {"nodeName": "talos-worker-01"},
    }
    data["pods"] = [pod]
    assert classify("primary", data) == (False, [])
    assert housekeeping_jobs(data)
    pod["metadata"]["ownerReferences"][0]["uid"] = "different-job"
    assert classify("primary", data)[1]


def test_playground_services_on_the_worker_do_not_hold_the_primary():
    data = inventory()
    for name in ["playground-router", "playground-ui"]:
        data["pods"].append(
            {
                "metadata": {
                    "namespace": "homelab-models",
                    "name": name + "-abc-xyz",
                    "ownerReferences": [
                        {"kind": "ReplicaSet", "name": name + "-abc", "uid": name, "controller": True}
                    ],
                },
                "spec": {"nodeName": "talos-worker-01"},
            }
        )
        data["replicasets"].append(
            {
                "metadata": {
                    "namespace": "homelab-models",
                    "name": name + "-abc",
                    "uid": name,
                    "ownerReferences": [
                        {"kind": "Deployment", "name": name, "uid": name + "-deploy", "controller": True}
                    ],
                }
            }
        )
    assert classify("primary", data) == (False, [])
    data["pods"][0]["metadata"]["ownerReferences"][0]["name"] = "other-abc"
    assert classify("primary", data)[1] == [
        "Active or unregistered pod: homelab-models/playground-router-abc-xyz"
    ]

