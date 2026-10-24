"""UID/CAS guarded quiescing of registered primary applications only."""

import uuid
from contextlib import nullcontext

from .config import INVENTORY
from .policy import AWAKE_ONLY, NODES, PLATFORM

# Quiesce order. Every Deployment in policy.PLATFORM must appear here or its pods
# survive the quiesce and the host never reaches "quiesced" (blocked at the deadline).
ORDER = [
    "playground-ui",
    "playground-router",
    "nexus",
    "nexus-postgres",
    "cnpg",
    "guest-capacity",
    "physical-capacity",
    "local-path-provisioner",
    "argocd-applicationset-controller",
    "argocd-application-controller",
    "argocd-server",
    "argocd-repo-server",
    "argocd-redis",
    "argocd-dex-server",
    "argocd-notifications-controller",
    "alloy",
    "grafana",
    "prometheus",
    "loki",
    "alertmanager",
]


def storage_identity(objects):
    result = {}
    for kind in ["pv", "pvc"]:
        for obj in objects[kind]:
            meta, spec = obj["metadata"], obj["spec"]
            key = kind + "/" + meta.get("namespace", "") + "/" + meta["name"]
            fields = (
                [
                    "claimRef",
                    "nodeAffinity",
                    "local",
                    "hostPath",
                    "persistentVolumeReclaimPolicy",
                ]
                if kind == "pv"
                else ["volumeName", "storageClassName"]
            )
            result[key] = {"uid": meta["uid"], **{k: spec.get(k) for k in fields}}
    return result


def storage_for_host(identity, host):
    """Exclude only local volumes proven to belong exclusively to another node.

    Shared and ambiguous storage stays protected; unbound claims are not, since
    nothing is stored behind them. Apply the same scope to old journals without
    rewriting the captured evidence.
    """
    excluded = set()
    for key, volume in identity.items():
        if not key.startswith("pv//") or not (
            volume.get("local") or volume.get("hostPath")
        ):
            continue
        affinity = volume.get("nodeAffinity") or {}
        terms = affinity.get("required", {}).get("nodeSelectorTerms", [])
        if len(terms) != 1:
            continue
        expressions = terms[0].get("matchExpressions", [])
        if len(expressions) != 1:
            continue
        selector = expressions[0]
        if (
            selector.get("key") == "kubernetes.io/hostname"
            and selector.get("operator") == "In"
            and selector.get("values")
            and NODES[host] not in selector["values"]
        ):
            excluded.add(key.removeprefix("pv//"))
    return {
        key: value
        for key, value in identity.items()
        if not (key.startswith("pv//") and key.removeprefix("pv//") in excluded)
        and not (key.startswith("pvc/") and value.get("volumeName") in excluded)
        # An unbound claim holds no data; acceptance fixtures leave and remove such
        # claims while a host sleeps, which must not refuse its restore.
        and not (key.startswith("pvc/") and not value.get("volumeName"))
    }


class Platform:
    def __init__(self, kube, management, journal):
        self.kube, self.management, self.journal = kube, management, journal
        self.interlocks = {}

    def record_name(self, host):
        return host + "-platform.json"

    def capture(self, host, objects):
        old = self.journal.read(self.record_name(host))
        if old and old["phase"] != "complete":
            raise RuntimeError("An unfinished platform operation requires recovery")
        node = next(n for n in objects["nodes"] if n["metadata"]["name"] == NODES[host])
        if node["metadata"]["uid"] != INVENTORY[host]["node_uid"] or node["spec"].get(
            "unschedulable"
        ):
            raise RuntimeError("Node identity changed or operator cordon is present")
        record = {
            "id": str(uuid.uuid4()),
            "phase": "captured",
            "node": node,
            "storage": storage_for_host(storage_identity(objects), host),
            "volume": self.management.storage(host),
            "objects": [],
        }
        if host == "primary":
            for resource in ["deployments", "statefulsets"]:
                for obj in objects[resource]:
                    m = obj["metadata"]
                    if (m["namespace"], m["name"]) in PLATFORM:
                        record["objects"].append({"resource": resource, "object": obj})
            record["cluster"] = next(
                o
                for o in objects["clusters"]
                if o["metadata"]["namespace"] == "homelab-data"
                and o["metadata"]["name"] == "apps-db"
            )
            record["cronjobs"] = [
                o
                for o in objects["cronjobs"]
                if (o["metadata"]["namespace"], o["metadata"]["name"]) in AWAKE_ONLY
            ]
        self.journal.write(self.record_name(host), record)
        return record

    def current(self, resource, before):
        m = before["metadata"]
        obj = self.kube.get(resource, m["name"], m.get("namespace"))
        if obj["metadata"]["uid"] != m["uid"]:
            raise RuntimeError(
                "Resource identity changed: " + resource + "/" + m["name"]
            )
        return obj

    def scale(self, entry, restoring, *, wait=True):
        resource, before = entry["resource"], entry["object"]
        obj = self.current(resource, before)
        original = before["spec"].get("replicas", 1)
        if obj["spec"].get("replicas", 1) not in {0, original}:
            raise RuntimeError("Concurrent replica change")
        target = original if restoring else 0
        if obj["spec"].get("replicas", 1) != target:
            self.kube.guarded(
                resource,
                obj,
                [{"op": "add", "path": "/spec/replicas", "value": target}],
            )
        ns, name = before["metadata"]["namespace"], before["metadata"]["name"]
        if not wait:
            return target == 0 or (
                obj["spec"].get("replicas", 1) == target
                and obj.get("status", {}).get("observedGeneration", 0)
                >= obj["metadata"].get("generation", 1)
                and obj.get("status", {}).get("readyReplicas", 0) >= target
                and obj.get("status", {}).get("updatedReplicas", target) >= target
            )
        if target:
            return self.kube.wait(
                "-n", ns, "rollout", "status", resource + "/" + name, "--timeout=20s"
            )
        else:
            # Waits are bounded; a slow or failed graceful termination blocks.
            selector = before["spec"]["selector"]
            if selector.get("matchExpressions"):
                raise RuntimeError("Unsupported application selector")
            labels = ",".join(k + "=" + v for k, v in selector["matchLabels"].items())
            return self.kube.wait(
                "-n", ns, "wait", "pods", "-l", labels, "--for=delete", "--timeout=20s"
            )

    def hibernate(self, record, restoring, *, wait=True):
        before = record["cluster"]
        obj = self.current("clusters.postgresql.cnpg.io", before)
        old = before["metadata"].get("annotations", {}).get("cnpg.io/hibernation")
        annotations = obj["metadata"].get("annotations", {}).copy()
        if annotations.get("cnpg.io/hibernation") not in {old, "on"}:
            raise RuntimeError("Concurrent hibernation change")
        target = old if restoring else "on"
        if target is None:
            annotations.pop("cnpg.io/hibernation", None)
        else:
            annotations["cnpg.io/hibernation"] = target
        if annotations != obj["metadata"].get("annotations", {}):
            self.kube.guarded(
                "clusters.postgresql.cnpg.io",
                obj,
                [{"op": "add", "path": "/metadata/annotations", "value": annotations}],
            )
        condition = "cnpg.io/hibernation=True" if target == "on" else "Ready=True"
        if not wait:
            return annotations == obj["metadata"].get("annotations", {}) and any(
                c.get("type") == condition.split("=")[0] and c.get("status") == "True"
                for c in obj.get("status", {}).get("conditions", [])
            )
        return self.kube.wait(
            "-n",
            "homelab-data",
            "wait",
            "cluster/apps-db",
            "--for=condition=" + condition,
            "--timeout=20s",
        )

    def schedules(self, record, restoring):
        for before in record.get("cronjobs", []):
            obj = self.current("cronjobs", before)
            original = before["spec"].get("suspend", False)
            if obj["spec"].get("suspend", False) not in {True, original}:
                raise RuntimeError("Concurrent schedule change")
            self.kube.guarded(
                "cronjobs",
                obj,
                [
                    {
                        "op": "add",
                        "path": "/spec/suspend",
                        "value": original if restoring else True,
                    }
                ],
            )

    def quiesce(self, host, objects):
        record = self.journal.read(self.record_name(host))
        if not record or record["phase"] == "complete":
            record = self.capture(host, objects)
        node = self.current("nodes", record["node"])
        annotations = node["metadata"].get("annotations", {}).copy()
        owned = annotations.get("homelab.tfdraw.dev/power-operation")
        if node["spec"].get("unschedulable") and owned != record["id"]:
            raise RuntimeError("Operator cordon is not owned by this operation")
        annotations["homelab.tfdraw.dev/power-operation"] = record["id"]
        annotations["homelab.tfdraw.dev/power-intent"] = "sleep"
        lock = self.interlocks.get(host)
        with lock.guard() if lock else nullcontext():
            self.kube.guarded(
                "nodes",
                node,
                [
                    {"op": "add", "path": "/spec/unschedulable", "value": True},
                    {
                        "op": "add",
                        "path": "/metadata/annotations",
                        "value": annotations,
                    },
                ],
            )
            self.schedules(record, False)
        entries = {e["object"]["metadata"]["name"]: e for e in record["objects"]}
        for name in ORDER:
            if (
                host == "primary"
                and name == "cnpg"
                and not self.shutdown_stage(
                    host,
                    record["cluster"],
                    "database",
                    lambda: self.hibernate(record, False),
                )
            ):
                return
            if name in entries:
                entry = entries[name]
                if not self.shutdown_stage(
                    host,
                    entry["object"],
                    entry["resource"],
                    lambda entry=entry: self.scale(entry, False),
                ):
                    return
        record["phase"] = "quiesced"
        self.journal.write(self.record_name(host), record)

    def shutdown_stage(self, host, obj, resource, callback):
        lock = self.interlocks.get(host)
        with lock.guard() if lock else nullcontext():
            if lock:
                lock.begin(
                    "platform-stage",
                    resource=resource,
                    object={
                        "metadata": {
                            k: v
                            for k, v in obj["metadata"].items()
                            if k in {"name", "namespace", "uid"}
                        }
                    },
                )
            result = callback()
            if lock and result:
                lock.settle("platform-stage")
            return result

    def stage_settled(self, host, objects, pending):
        before = pending["object"]
        resource = pending["resource"]
        if resource == "database":
            current = self.current("clusters.postgresql.cnpg.io", before)
            return current["metadata"].get("annotations", {}).get(
                "cnpg.io/hibernation"
            ) == "on" and any(
                c.get("type") == "cnpg.io/hibernation" and c.get("status") == "True"
                for c in current.get("status", {}).get("conditions", [])
            )
        current = self.current(resource, before)
        selector = current["spec"]["selector"]
        if selector.get("matchExpressions") or not selector.get("matchLabels"):
            return False
        return current["spec"].get("replicas", 1) == 0 and not any(
            p["metadata"].get("namespace") == current["metadata"].get("namespace")
            and all(
                p["metadata"].get("labels", {}).get(k) == v
                for k, v in selector["matchLabels"].items()
            )
            for p in objects["pods"]
        )

    def restore(self, host, objects):
        record = self.journal.read(self.record_name(host))
        if not record or record["phase"] == "complete":
            return
        observed_storage = storage_identity(objects)
        if (
            any(
                observed_storage.get(k) != v
                for k, v in storage_for_host(record["storage"], host).items()
            )
            or self.management.storage(host) != record["volume"]
        ):
            raise RuntimeError("Protected storage identity or mount changed")
        node = self.current("nodes", record["node"])
        annotations = node["metadata"].get("annotations", {}).copy()
        if (
            node["spec"].get("unschedulable")
            and annotations.get("homelab.tfdraw.dev/power-operation") != record["id"]
        ):
            raise RuntimeError("Refusing to clear an unrelated operator cordon")
        self.kube.guarded(
            "nodes",
            node,
            [{"op": "add", "path": "/spec/unschedulable", "value": False}],
        )
        entries = {e["object"]["metadata"]["name"]: e for e in record["objects"]}
        # Start every independent chain before waiting on any one service.
        # Reconciliation observes readiness without a serial 20-second wait per
        # component. UID/CAS guards and the journal remain authoritative.
        dependencies = {
            "cnpg": {"local-path-provisioner"},
            "nexus-postgres": {"local-path-provisioner"},
            "nexus": {"nexus-postgres"},
            "argocd-server": {"argocd-redis", "argocd-repo-server"},
            "argocd-application-controller": {"argocd-redis", "argocd-repo-server"},
        }
        ready = set()
        pending = dict(entries)
        for _ in range(len(entries) + 1):
            progress = False
            for name, entry in list(pending.items()):
                required = (
                    dependencies.get(
                        name,
                        {"local-path-provisioner"}
                        if name != "local-path-provisioner"
                        else set(),
                    )
                    & entries.keys()
                )
                if not required <= ready:
                    continue
                if self.scale(entry, True, wait=False):
                    ready.add(name)
                del pending[name]
                progress = True
            if not progress:
                break
        database_ready = "cluster" not in record
        if "cluster" in record and ("cnpg" not in entries or "cnpg" in ready):
            database_ready = self.hibernate(record, True, wait=False)
        record["restoration_ready"] = sorted(ready)
        self.journal.write(self.record_name(host), record)
        if pending or ready != entries.keys() or not database_ready:
            return
        self.schedules(record, True)
        node = self.current("nodes", record["node"])
        annotations = node["metadata"].get("annotations", {}).copy()
        if node["spec"].get("unschedulable"):
            raise RuntimeError("Node was cordoned during restoration")
        if annotations.get("homelab.tfdraw.dev/power-operation") == record["id"]:
            operations = [
                {
                    "op": "remove",
                    "path": "/metadata/annotations/homelab.tfdraw.dev~1power-operation",
                }
            ]
            if "homelab.tfdraw.dev/power-intent" in annotations:
                operations.append(
                    {
                        "op": "remove",
                        "path": "/metadata/annotations/homelab.tfdraw.dev~1power-intent",
                    }
                )
            self.kube.guarded("nodes", node, operations)
        record["phase"] = "complete"
        self.journal.write(self.record_name(host), record)
