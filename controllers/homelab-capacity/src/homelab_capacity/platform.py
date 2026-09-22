"""UID/CAS guarded quiescing of registered primary applications only."""

import uuid
from .config import INVENTORY
from .policy import PLATFORM, AWAKE_ONLY, NODES

ORDER = [
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


class Platform:
    def __init__(self, kube, management, journal):
        self.kube, self.management, self.journal = kube, management, journal

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
            "storage": storage_identity(objects),
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

    def scale(self, entry, restoring):
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

    def hibernate(self, record, restoring):
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
        self.kube.guarded(
            "nodes",
            node,
            [
                {"op": "add", "path": "/spec/unschedulable", "value": True},
                {"op": "add", "path": "/metadata/annotations", "value": annotations},
            ],
        )
        self.schedules(record, False)
        entries = {e["object"]["metadata"]["name"]: e for e in record["objects"]}
        for name in ORDER:
            if host == "primary" and name == "cnpg":
                if not self.hibernate(record, False):
                    return
            if name in entries:
                if not self.scale(entries[name], False):
                    return
        record["phase"] = "quiesced"
        self.journal.write(self.record_name(host), record)

    def restore(self, host, objects):
        record = self.journal.read(self.record_name(host))
        if not record or record["phase"] == "complete":
            return
        observed_storage = storage_identity(objects)
        if (
            any(observed_storage.get(k) != v for k, v in record["storage"].items())
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
        restore_order = [
            "local-path-provisioner",
            "cnpg",
            "nexus-postgres",
            "nexus",
        ] + list(reversed(ORDER))
        done = set()
        for name in restore_order:
            if name not in entries or name in done:
                continue
            if not self.scale(entries[name], True):
                return
            done.add(name)
            if name == "cnpg":
                if not self.hibernate(record, True):
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
