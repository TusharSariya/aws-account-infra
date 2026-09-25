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


def owned(workload):
    """Only the retained-server queue is inside this controller's power domain."""
    return (
        workload.get("status", {}).get("admission", {}).get("clusterQueue")
        == "homelab-compute"
    )


def assigned_hosts(workload):
    if (
        not owned(workload)
        or finished(workload)
        or workload["metadata"].get("deletionTimestamp")
    ):
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
    if not owned(workload) or not check or finished(workload):
        return None
    invalid = None
    try:
        needed = dependencies(workload)
    except ValueError as exc:
        needed, invalid = set(), str(exc)
    if not needed and not invalid:
        return None
    # Never evict already admitted work in response to a transient observation.
    if any(
        c["type"] == "Admitted" and c["status"] == "True"
        for c in status.get("conditions", [])
    ):
        return None
    state = "Ready" if not invalid and needed <= ready_hosts else "Pending"
    message = invalid or (
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


def reconcile_quotas(kube, budgets):
    """Only runtime nominalQuota fields belong to this controller."""
    queue = kube.get("clusterqueues.kueue.x-k8s.io", "homelab-compute")
    operations = []
    for gi, group in enumerate(queue["spec"]["resourceGroups"]):
        for fi, flavor in enumerate(group["flavors"]):
            host = FLAVORS[flavor["name"]]
            for ri, resource in enumerate(flavor["resources"]):
                value = budgets.get(host, {}).get(resource["name"], "0")
                if str(resource["nominalQuota"]) != value:
                    operations.append(
                        {
                            "op": "replace",
                            "path": f"/spec/resourceGroups/{gi}/flavors/{fi}/resources/{ri}/nominalQuota",
                            "value": value,
                        }
                    )
    if operations:
        kube.guarded("clusterqueues.kueue.x-k8s.io", queue, operations)


def pending_hosts(workload):
    """Wake only explicitly registered local queues, even before reservation.

    Node selectors/required affinity remain authoritative at Kueue admission.
    Unassigned ARC demand first restores its primary registry dependency.
    """
    if (
        finished(workload)
        or workload["metadata"].get("deletionTimestamp")
        or workload.get("status", {}).get("admission")
    ):
        return set()
    key = (workload["metadata"]["namespace"], workload.get("spec", {}).get("queueName"))
    if key not in {
        ("arc-runners", "ci"),
        ("homelab-jobs", "argo"),
        ("homelab-models", "ai"),
    }:
        return set()
    selectors = [
        p["template"]["spec"].get("nodeSelector", {}).get("kubernetes.io/hostname")
        for p in workload.get("spec", {}).get("podSets", [])
    ]
    if selectors and all(n == "talos-worker-02" for n in selectors):
        return {"primary", "secondary"} if key[0] == "arc-runners" else {"secondary"}
    if key[0] == "homelab-models" or "talos-worker-01" in selectors:
        return {"primary"}
    return {"primary"}


def admission_budget(workloads, budgets, ready):
    """Select fitting reservations against this tick's capacity before readiness.

    Kueue normally accounts for these resources. Rechecking closes the window
    between a service commitment increase and old reservations being admitted.
    """
    from .capacity import quantity
    from .effective import RESOURCES

    available = {
        h: {r: quantity(budgets.get(h, {}).get(r, "0")) for r in RESOURCES}
        for h in ready
    }

    def usage(w):
        totals = {}
        for assignment in (
            w.get("status", {}).get("admission", {}).get("podSetAssignments", [])
        ):
            flavors = assignment.get("flavors", {})
            hosts = {FLAVORS[f] for f in flavors.values()}
            if len(hosts) != 1:
                raise ValueError("All resources must use one registered worker")
            host = next(iter(hosts))
            amounts = totals.setdefault(host, {r: quantity("0") for r in RESOURCES})
            for r in RESOURCES:
                amounts[r] += quantity(
                    assignment.get("resourceUsage", {}).get(
                        r, assignment.get("count", 1) if r == "pods" else "0"
                    )
                )
        return totals

    candidates = []
    for w in workloads:
        if not owned(w) or finished(w):
            continue
        if any(
            c["type"] == "Admitted" and c["status"] == "True"
            for c in w.get("status", {}).get("conditions", [])
        ):
            for host, amounts in usage(w).items():
                if host in available:
                    for r, amount in amounts.items():
                        available[host][r] -= amount
        elif not w["metadata"].get("deletionTimestamp"):
            candidates.append(w)
    allowed = set()
    for w in sorted(
        candidates,
        key=lambda w: (
            w["metadata"].get("creationTimestamp", ""),
            w["metadata"]["uid"],
        ),
    ):
        demand = usage(w)
        if (
            demand
            and dependencies(w) <= ready
            and all(
                h in available and all(v <= available[h][r] for r, v in amounts.items())
                for h, amounts in demand.items()
            )
        ):
            allowed.add(w["metadata"]["uid"])
            for h, amounts in demand.items():
                for r, v in amounts.items():
                    available[h][r] -= v
    return allowed


def unreserved_demand(objects, potential):
    """Prefer primary, then eligible secondary, without requiring a reservation."""
    from .capacity import quantity, requests
    from .config import INVENTORY
    from .effective import RESOURCES, eligible

    nodes = {
        host: next(
            (n for n in objects["nodes"] if n["metadata"]["name"] == entry["node"]),
            None,
        )
        for host, entry in INVENTORY.items()
    }
    free = {
        h: {r: quantity(potential.get(h, {}).get(r, "0")) for r in RESOURCES}
        for h in nodes
    }
    for w in objects["workloads"]:
        if not owned(w) or finished(w):
            continue
        for a in w.get("status", {}).get("admission", {}).get("podSetAssignments", []):
            for r in RESOURCES:
                flavor = a.get("flavors", {}).get(r)
                if flavor in FLAVORS:
                    free[FLAVORS[flavor]][r] -= quantity(
                        a.get("resourceUsage", {}).get(
                            r, a.get("count", 1) if r == "pods" else 0
                        )
                    )
    demand = set()
    for w in sorted(
        objects["workloads"], key=lambda w: w["metadata"].get("creationTimestamp", "")
    ):
        if not pending_hosts(w):
            continue
        podsets = w.get("spec", {}).get("podSets", [])
        candidates = [
            h
            for h, n in nodes.items()
            if n and all(eligible(p["template"]["spec"], n) for p in podsets)
        ]
        if not candidates:
            continue
        amounts = {
            r: sum(
                (
                    quantity(p.get("count", 1))
                    * (1 if r == "pods" else requests(p["template"], r))
                    for p in podsets
                ),
                quantity(0),
            )
            for r in RESOURCES
        }
        fits = [
            h for h in candidates if all(amounts[r] <= free[h][r] for r in RESOURCES)
        ]
        # No verified budget yet: wake the first eligible host to measure it.
        host = (fits or candidates)[0]
        demand.add(host)
        if w["metadata"]["namespace"] == "arc-runners":
            demand.add("primary")
        for r in RESOURCES:
            free[host][r] -= amounts[r]
    return demand
