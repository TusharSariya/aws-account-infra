from homelab_capacity.kueue import CHECK, admission_patch, dependencies
import pytest


def workload(flavor="homelab-secondary", namespace="arc-runners"):
    return {
        "metadata": {
            "namespace": namespace,
            "uid": "original",
            "resourceVersion": "12",
        },
        "status": {
            "admission": {"podSetAssignments": [{"flavors": {"cpu": flavor}}]},
            "admissionChecks": [{"name": CHECK, "state": "Pending"}],
        },
    }


def test_secondary_ci_waits_for_primary_nexus_too():
    w = workload()
    assert dependencies(w) == {"primary", "secondary"}
    assert admission_patch(w, {"secondary"})[-1]["value"][0]["state"] == "Pending"
    patch = admission_patch(w, {"primary", "secondary"})
    assert patch[0]["value"] == "original" and patch[1]["value"] == "12"
    assert patch[-1]["value"][0]["state"] == "Ready"


def test_portable_non_ci_can_use_secondary_alone():
    assert dependencies(workload(namespace="homelab-jobs")) == {"secondary"}


def test_unknown_flavor_blocks_instead_of_waking_wrong_host():
    with pytest.raises(ValueError, match="Unregistered"):
        dependencies(workload("unregistered"))


def test_finished_and_already_admitted_are_not_mutated():
    w = workload()
    w["status"]["conditions"] = [{"type": "Admitted", "status": "True"}]
    assert admission_patch(w, set()) is None
    w["status"]["conditions"] = [{"type": "Finished", "status": "True"}]
    assert dependencies(w) == set()
