"""Fail-closed workload classification for retained hosts.

Only explicitly registered background controllers are quiescible. Unknown pods,
unfinished jobs, and missing observations prevent automatic host retirement.
"""

from .kueue import dependencies

NODES = {"primary": "talos-worker-01", "secondary": "talos-worker-02"}
AWAKE_ONLY = {
    ("homelab-cache", "cache-monitor"),
    ("homelab-data", "apps-db-backup-monitor"),
}
WAKE_SCHEDULES = {("homelab-data", "apps-db-backup"): "primary"}
PLATFORM = {
    ("homelab-cache", "nexus"),
    ("homelab-cache", "nexus-postgres"),
    ("cnpg-system", "cnpg"),
    ("local-path-storage", "local-path-provisioner"),
    ("homelab-platform", "guest-capacity"),
    ("homelab-platform", "physical-capacity"),
    *(
        (
            ("monitoring", n)
            for n in ["prometheus", "loki", "grafana", "alloy", "alertmanager"]
        )
    ),
    *(
        (
            ("argocd", n)
            for n in [
                "argocd-server",
                "argocd-repo-server",
                "argocd-redis",
                "argocd-application-controller",
                "argocd-applicationset-controller",
                "argocd-dex-server",
                "argocd-notifications-controller",
            ]
        )
    ),
}
DAEMONSETS = {("kube-system", n) for n in ["cilium", "cilium-envoy", "kube-proxy"]}


def owner(obj):
    return next(
        (o for o in obj["metadata"].get("ownerReferences", []) if o.get("controller")),
        None,
    )


def done(obj):
    return obj.get("status", {}).get("phase") in {"Succeeded", "Failed"} or any(
        c.get("type") in {"Complete", "Failed"} and c.get("status") == "True"
        for c in obj.get("status", {}).get("conditions", [])
    )


def housekeeping_jobs(objects):
    return {
        (j["metadata"]["namespace"], j["metadata"].get("uid"))
        for j in objects["jobs"]
        if not done(j)
        and owner(j)
        and owner(j)["kind"] == "CronJob"
        and (j["metadata"]["namespace"], owner(j)["name"]) in AWAKE_ONLY
    }


def classify(host, objects, *, verified_ai_idle=False):
    """Input is a complete API snapshot, not an eventually-empty partial list."""
    required = {"pods", "replicasets", "jobs", "workloads", "backups", "applications"}
    if not required <= objects.keys():
        return False, ["Incomplete Kubernetes inventory"]
    demand, blockers = False, []
    replicasets = {
        (o["metadata"]["namespace"], o["metadata"]["name"]): o
        for o in objects["replicasets"]
    }
    # Kueue's Pod integration omits template labels from Workloads. Match the
    # actual Pod owner UID instead; names/queue names alone are insufficient.
    idle_ai_pods = {
        p["metadata"]["uid"]
        for p in objects["pods"]
        if p["metadata"]["namespace"] == "homelab-models"
        and p["metadata"].get("labels", {}).get("app") == "ai-runtime"
        and not done(p)
    }
    for workload in objects["workloads"]:
        parent = owner(workload)
        ai = (
            workload["metadata"]["namespace"] == "homelab-models"
            and parent
            and parent["kind"] == "Pod"
            and parent.get("uid") in idle_ai_pods
        )
        if verified_ai_idle and ai:
            continue
        if host in dependencies(workload):
            demand = True
    for job in objects["jobs"]:
        if done(job) or job["metadata"].get("deletionTimestamp"):
            continue
        parent = owner(job)
        key = (
            (job["metadata"]["namespace"], parent["name"])
            if parent and parent["kind"] == "CronJob"
            else None
        )
        if WAKE_SCHEDULES.get(key) == host:
            demand = True
    for backup in objects["backups"]:
        if host == "primary" and backup.get("status", {}).get("phase") not in {
            "completed",
            "failed",
        }:
            demand = True
            blockers.append("Database backup unfinished")
    if host == "primary":
        for app in objects["applications"]:
            if app.get("spec", {}).get("syncPolicy", {}).get("automated") is not None:
                blockers.append(
                    "Argo automatic reconciliation requires a registered power policy"
                )
    housekeeping = housekeeping_jobs(objects)
    for pod in objects["pods"]:
        if done(pod):
            continue
        parent = owner(pod)
        # These fixed housekeeping jobs never constitute application demand, but
        # retirement_ready below requires every unfinished job to finish first.
        if (
            host == "primary"
            and parent
            and parent["kind"] == "Job"
            and (pod["metadata"]["namespace"], parent.get("uid")) in housekeeping
        ):
            continue
        if (
            parent
            and parent["kind"] == "DaemonSet"
            and (pod["metadata"]["namespace"], parent["name"]) in DAEMONSETS
        ):
            continue
        if not pod["spec"].get("nodeName"):
            selectors = pod["spec"].get("nodeSelector", {})
            # Laptop services do not consume application host capacity. Queued
            # compute obtains its wake dependency from the Workload assignment.
            if "node-role.kubernetes.io/control-plane" in selectors:
                continue
            if "kueue.x-k8s.io/queue-name" in pod["metadata"].get("labels", {}):
                continue
            blockers.append(
                "Unregistered pending pod: "
                + pod["metadata"]["namespace"]
                + "/"
                + pod["metadata"]["name"]
            )
            continue
        if pod["spec"]["nodeName"] != NODES[host]:
            continue
        ns, name = pod["metadata"]["namespace"], pod["metadata"]["name"]
        parent = owner(pod)
        if (
            parent
            and parent["kind"] == "DaemonSet"
            and (ns, parent["name"]) in DAEMONSETS
        ):
            continue
        if parent and parent["kind"] == "ReplicaSet":
            rs = replicasets.get((ns, parent["name"]))
            if rs and rs["metadata"]["uid"] == parent["uid"]:
                parent = owner(rs)
        if (
            verified_ai_idle
            and parent
            and parent["kind"] == "Deployment"
            and (ns, parent["name"]) == ("homelab-models", "ai-runtime")
        ):
            continue
        if host == "primary" and parent:
            if (
                parent["kind"] in {"Deployment", "StatefulSet"}
                and (ns, parent["name"]) in PLATFORM
            ):
                continue
            if parent["kind"] == "Cluster" and (ns, parent["name"]) == (
                "homelab-data",
                "apps-db",
            ):
                continue
        blockers.append("Active or unregistered pod: " + ns + "/" + name)
    return demand, blockers
