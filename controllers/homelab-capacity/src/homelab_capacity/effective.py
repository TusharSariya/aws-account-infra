"""Derive Kueue budgets from allocatable resources and desired service commitments.

Measurements authorize new admission only. They never revoke running workloads.
"""

from datetime import datetime, timezone
from decimal import Decimal

from .capacity import quantity, requests

RESOURCES = ("cpu", "memory", "ephemeral-storage", "pods")


def compute(pod):
    return "kueue.x-k8s.io/queue-name" in pod.get("metadata", {}).get("labels", {})


def active(pod):
    return pod.get("status", {}).get("phase") not in ("Succeeded", "Failed")


def reserved(pod, objects):
    """Queued Pods without a live reservation still consume physical capacity."""
    if not compute(pod):
        return False
    owners = {pod["metadata"]["uid"]} | {
        o["uid"] for o in pod["metadata"].get("ownerReferences", [])
    }
    for workload in objects.get("workloads", []):
        if not workload.get("status", {}).get("admission"):
            continue
        if any(
            c["type"] == "Finished" and c["status"] == "True"
            for c in workload.get("status", {}).get("conditions", [])
        ):
            continue
        if any(
            o.get("uid") in owners
            for o in workload["metadata"].get("ownerReferences", [])
        ):
            return True
    return False


def eligible(spec, node):
    if spec.get("nodeName"):
        return spec["nodeName"] == node["metadata"]["name"]
    labels = node["metadata"].get("labels", {}) | {
        "kubernetes.io/hostname": node["metadata"]["name"]
    }
    if any(labels.get(k) != v for k, v in spec.get("nodeSelector", {}).items()):
        return False
    terms = (
        spec.get("affinity", {})
        .get("nodeAffinity", {})
        .get("requiredDuringSchedulingIgnoredDuringExecution", {})
        .get("nodeSelectorTerms")
    )
    if terms is not None:

        def match(term):
            if term.get("matchFields"):
                # Unknown field matching reserves conservatively.
                return True
            for item in term.get("matchExpressions", []):
                value = labels.get(item["key"])
                op = item["operator"]
                values = item.get("values", [])
                if op == "In" and value not in values:
                    return False
                if op == "NotIn" and value in values:
                    return False
                if op == "Exists" and value is None:
                    return False
                if op == "DoesNotExist" and value is not None:
                    return False
                if op in ("Gt", "Lt"):
                    try:
                        if not (
                            int(value) > int(values[0])
                            if op == "Gt"
                            else int(value) < int(values[0])
                        ):
                            return False
                    except (ValueError, TypeError, IndexError):
                        return False
            return True

        if not any(match(term) for term in terms):
            return False
    return True


def commitments(node, objects, record=None):
    pods = [
        p
        for p in objects["pods"]
        if active(p)
        and not reserved(p, objects)
        and not (compute(p) and not p["spec"].get("nodeName"))
        and (
            p["spec"].get("nodeName") == node["metadata"]["name"]
            or (not p["spec"].get("nodeName") and eligible(p["spec"], node))
        )
    ]
    totals = {
        r: sum((requests(p, r) for p in pods), Decimal(0)) for r in RESOURCES[:-1]
    }
    totals["pods"] = Decimal(len(pods))
    saved = {
        (e["resource"], e["object"]["metadata"]["uid"]): e["object"]
        for e in (record or {}).get("objects", [])
        if (record or {}).get("phase") != "complete"
    }
    for kind in ("deployments", "statefulsets", "daemonsets", "clusters"):
        for current in objects.get(kind, []):
            obj = saved.get((kind, current["metadata"]["uid"]), current)
            spec = current["spec"]
            if kind == "clusters":
                template = {
                    "metadata": {},
                    "spec": {
                        "containers": [{"resources": spec.get("resources", {})}],
                        "nodeSelector": spec.get("affinity", {}).get(
                            "nodeSelector", {}
                        ),
                    },
                }
                count = spec.get("instances", 1)
            else:
                template = spec["template"]
                count = max(spec.get("replicas", 1), obj["spec"].get("replicas", 1))
                if kind == "daemonsets":
                    count = 1
            if compute(template) or not eligible(template["spec"], node):
                continue
            # Template labels are stable across ReplicaSet replacements; sum all
            # live matching Pods, including surge Pods, then reserve missing slots.
            labels = template.get("metadata", {}).get("labels", {})
            matching = [
                p
                for p in pods
                if p["metadata"].get("namespace") == obj["metadata"].get("namespace")
                and (
                    (
                        labels
                        and all(
                            p["metadata"].get("labels", {}).get(k) == v
                            for k, v in labels.items()
                        )
                    )
                    or (
                        kind == "clusters"
                        and p["metadata"].get("labels", {}).get("cnpg.io/cluster")
                        == obj["metadata"]["name"]
                    )
                )
            ]
            missing = max(0, count - len(matching))
            totals["pods"] += missing
            for r in RESOURCES[:-1]:
                # Include template increases before rollout Pods appear.
                totals[r] += max(
                    Decimal(0),
                    requests(template, r) * count
                    - sum((requests(p, r) for p in matching), Decimal(0)),
                )
    return totals


def effective(node, objects, summary, record=None, *, now=None, storage_headroom="0"):
    now = now or datetime.now(timezone.utc)
    if summary["node"]["nodeName"] != node["metadata"]["name"]:
        raise ValueError("Node statistics identity mismatch")
    if not any(
        c["type"] == "Ready" and c["status"] == "True"
        for c in node["status"]["conditions"]
    ):
        raise ValueError("Fresh Ready node required")
    samples = [summary["node"]["fs"], summary["node"]["runtime"]["imageFs"]]
    for sample in samples:
        age = (
            now - datetime.fromisoformat(sample["time"].replace("Z", "+00:00"))
        ).total_seconds()
        if not 0 <= age <= 30:
            raise ValueError("Fresh filesystem statistics required")
    committed = commitments(node, objects, record)
    alloc = {r: quantity(node["status"]["allocatable"][r]) for r in RESOURCES}
    quotas = {
        r: max(Decimal(0), alloc[r] - committed[r]) for r in ("cpu", "memory", "pods")
    }
    local = [
        p
        for p in objects["pods"]
        if active(p) and p["spec"].get("nodeName") == node["metadata"]["name"]
    ]
    measured = {
        p["podRef"]["uid"]: quantity(p.get("ephemeral-storage", {}).get("usedBytes", 0))
        for p in summary.get("pods", [])
    }
    compute_used = sum(
        (
            min(
                measured.get(p["metadata"]["uid"], Decimal(0)),
                requests(p, "ephemeral-storage"),
            )
            for p in local
            if reserved(p, objects)
        ),
        Decimal(0),
    )
    platform_used = sum(
        (
            min(
                measured.get(p["metadata"]["uid"], Decimal(0)),
                requests(p, "ephemeral-storage"),
            )
            for p in local
            if not reserved(p, objects)
        ),
        Decimal(0),
    )
    growth = max(Decimal(0), committed["ephemeral-storage"] - platform_used)
    # nodefs/imagefs can share a device. Taking the smaller remaining budget
    # checks both and never adds their free bytes or double-counts image usage.
    remaining = min(
        min(
            quantity(s["availableBytes"]),
            alloc["ephemeral-storage"] - quantity(s["usedBytes"]),
        )
        for s in samples
    )
    quotas["ephemeral-storage"] = max(
        Decimal(0), remaining + compute_used - growth - quantity(storage_headroom)
    )
    result = {
        r: str(v.quantize(Decimal(".001")) if r == "cpu" else int(v))
        for r, v in quotas.items()
    }
    return {
        "quotas": result,
        "commitments": {r: str(v) for r, v in committed.items()},
        "allocatable": {r: str(v) for r, v in alloc.items()},
        "observed_at": now.timestamp(),
    }
