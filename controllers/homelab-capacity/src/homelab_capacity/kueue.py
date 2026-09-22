"""Kueue admission protocol for retained, bounded worker capacity."""

from datetime import datetime, timezone

CHECK = "homelab-host-ready"
CONTROLLER = "homelab.tfdraw.dev/retained-host-power"
FLAVORS = {"homelab-worker": "primary", "homelab-secondary": "secondary"}


def finished(workload):
    return any(
        c["type"] == "Finished" and c["status"] == "True"
        for c in workload.get("status", {}).get("conditions", [])
    )


def assigned_hosts(workload):
    if finished(workload) or workload["metadata"].get("deletionTimestamp"):
        return set()
    admission = workload.get("status", {}).get("admission")
    if not admission:
        return set()
    hosts = set()
    for assignment in admission.get("podSetAssignments", []):
        if assignment.get("count", 1) <= 0:
            continue
        for flavor in assignment.get("flavors", {}).values():
            if flavor not in FLAVORS:
                raise ValueError("Unregistered resource flavor: " + flavor)
            hosts.add(FLAVORS[flavor])
    return hosts


def dependencies(workload):
    hosts = assigned_hosts(workload)
    if hosts and workload["metadata"]["namespace"] == "arc-runners":
        hosts.add("primary")  # Nexus registry dependency, even on secondary.
    return hosts


def admission_patch(workload, ready_hosts):
    """CAS the entire status with UID/resourceVersion tests; preserve other checks."""
    import copy

    status = workload.get("status", {})
    checks = copy.deepcopy(status.get("admissionChecks", []))
    check = next((c for c in checks if c["name"] == CHECK), None)
    needed = dependencies(workload)
    if not check or not needed or finished(workload):
        return None
    # Never evict already admitted work in response to a transient observation.
    if any(
        c["type"] == "Admitted" and c["status"] == "True"
        for c in status.get("conditions", [])
    ):
        return None
    state = "Ready" if needed <= ready_hosts else "Pending"
    message = (
        "Worker and dependencies ready"
        if state == "Ready"
        else "Waiting for: " + ", ".join(sorted(needed - ready_hosts))
    )
    if check.get("state") == state and check.get("message") == message:
        return None
    check.update(
        state=state,
        message=message,
        lastTransitionTime=datetime.now(timezone.utc).isoformat(),
    )
    return [
        {"op": "test", "path": "/metadata/uid", "value": workload["metadata"]["uid"]},
        {
            "op": "test",
            "path": "/metadata/resourceVersion",
            "value": workload["metadata"]["resourceVersion"],
        },
        {"op": "add", "path": "/status/admissionChecks", "value": checks},
    ]
