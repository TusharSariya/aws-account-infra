"""Bounded external observer and run-owned Kubernetes resource operations."""

from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path
import re
import subprocess
import time
from datetime import datetime, timezone
from decimal import Decimal
import xml.etree.ElementTree as ET

LABEL = "validation.homelab.tfdraw.dev/run"
CASE = "validation.homelab.tfdraw.dev/case"
VERSION = "2.8.5"
# Namespace and PV deletion are deliberately absent. PVCs must use Delete policy.
RESOURCES = {
    "jobs": ("batch/v1", "Job"),
    "deployments": ("apps/v1", "Deployment"),
    "pods": ("v1", "Pod"),
    "services": ("v1", "Service"),
    "networkpolicies": ("networking.k8s.io/v1", "NetworkPolicy"),
    "poddisruptionbudgets": ("policy/v1", "PodDisruptionBudget"),
    "persistentvolumeclaims": ("v1", "PersistentVolumeClaim"),
    "workloads": ("kueue.x-k8s.io/v1beta2", "Workload"),
}


class Blocked(RuntimeError):
    """Missing prerequisite, never a passing test."""


def quantity(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(Ki|Mi|Gi|Ti|m|k|M|G|T)?", str(value))
    if not match:
        raise ValueError(f"Unsupported nonnegative quantity: {value}")
    factors = {
        "": 1,
        "m": 0.001,
        "k": 1000,
        "M": 10**6,
        "G": 10**9,
        "T": 10**12,
        **{u + "i": 1024**i for i, u in enumerate("KMGT", 1)},
    }
    return Decimal(match[1]) * Decimal(str(factors[match[2] or ""]))


def ready(obj):
    return any(
        c["type"] == "Ready" and c["status"] == "True"
        for c in obj.get("status", {}).get("conditions", [])
    )


def condition(obj, name):
    return any(
        c["type"] == name and c["status"] == "True"
        for c in obj.get("status", {}).get("conditions", [])
    )


def path(value):
    return Path(value).expanduser()


def read_json(filename):
    return json.loads(path(filename).read_text())


def save(filename, value):
    filename = Path(filename)
    tmp = filename.with_suffix(filename.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    tmp.replace(filename)


def load_profile(filename):
    p = read_json(filename)
    for key in (
        "cluster",
        "server",
        "namespace",
        "queue",
        "cluster_queue",
        "worker_selector",
        "slots",
    ):
        if not p.get(key):
            raise ValueError(f"Profile requires {key}")
    if p["kube_burner_version"] != VERSION:
        raise ValueError(f"Supported kube-burner version is {VERSION}")
    for n in p["timeouts"].values():
        if not isinstance(n, int) or n <= 0:
            raise ValueError("Timeouts must be positive integer seconds")
    load = p["load"]
    if any(
        not isinstance(n, int) or n <= 0 or n > p["budgets"]["max_jobs"]
        for n in [*load["bursts"], load["sustained_jobs"]]
    ):
        raise ValueError("Job counts exceed the profile budget")
    for k, v in (
        ("cpu", "cpu"),
        ("memory", "memory"),
        ("ephemeral-storage", "scratch"),
    ):
        if not 0 < quantity(load[v]) <= quantity(p["budgets"][k]):
            raise ValueError(f"Invalid {v} request")
    if not 0 < load["job_seconds"] <= 600 or not 0 < load["sustained_seconds"] <= 3600:
        raise ValueError("Load durations outside bounded range")
    if not re.fullmatch(r".+@sha256:[0-9a-f]{64}", p["image"]):
        raise ValueError("Probe image must be digest pinned")
    return p


def command(args, *, data=None, timeout=30, env=None):
    result = subprocess.run(
        [str(a) for a in args],
        input=data,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )
    if result.returncode:
        raise RuntimeError(
            f"{args[0]} exited {result.returncode}: {result.stderr[-2000:]}"
        )
    return result.stdout


class Cluster:
    def __init__(self, profile):
        self.p = profile
        self.k = [
            str(path(profile["kubectl"])),
            "--kubeconfig",
            str(path(profile["kubeconfig"])),
            "--request-timeout=15s",
        ]

    def call(self, *args, data=None, timeout=30):
        return command(self.k + list(args), data=data, timeout=timeout)

    def get(self, resource, name=None, namespace=None, selector=None):
        args = ["get", resource]
        if name:
            args.append(name)
        if namespace:
            args += ["-n", namespace]
        if selector:
            args += ["-l", selector]
        obj = json.loads(self.call(*args, "-o", "json"))
        return obj if name else obj["items"]

    def identity(self, expected_uid=None):
        config = json.loads(self.call("config", "view", "--minify", "-o", "json"))
        cluster = config["clusters"][0]
        if (cluster["name"], cluster["cluster"]["server"]) != (
            self.p["cluster"],
            self.p["server"],
        ):
            raise Blocked("Kubeconfig does not identify the isolated target")
        uid = self.get("namespace", "kube-system")["metadata"]["uid"]
        if expected_uid and uid != expected_uid:
            raise Blocked("Cluster UID changed")
        if self.p.get("kube_system_uid") and uid != self.p["kube_system_uid"]:
            raise Blocked("Cluster UID differs from profile")
        return uid

    def delete_owned(self, obj, run_id, attempts=5, guard=None):
        m = obj["metadata"]
        if m.get("labels", {}).get(LABEL) != run_id:
            raise RuntimeError("Refusing deletion of foreign resource")
        resource = next(
            (r for r, (_, k) in RESOURCES.items() if k == obj["kind"]), None
        )
        if not resource:
            raise RuntimeError("Resource kind is outside cleanup allowlist")
        prefix = "job-" + run_id + "-" if resource == "workloads" else run_id + "-"
        if not m.get("name", "").startswith(prefix):
            raise RuntimeError("Resource name is not owned by this run")
        if guard:
            guard(obj)
        api = obj["apiVersion"]
        prefix = "/api/v1" if api == "v1" else "/apis/" + api
        uri = f"{prefix}/namespaces/{m['namespace']}/{resource}/{m['name']}"
        # Server-side identity precondition prevents name-reuse races.
        options = {
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "propagationPolicy": "Foreground",
            "preconditions": {"uid": m["uid"], "resourceVersion": m["resourceVersion"]},
        }
        try:
            self.call("delete", "--raw", uri, "-f", "-", data=json.dumps(options))
        except RuntimeError as exc:
            if "(NotFound)" in str(exc):
                return  # Already garbage-collected after its parent was deleted.
            if "(Conflict)" not in str(exc) or attempts <= 1:
                raise
            try:
                current = self.get(resource, m["name"], m["namespace"])
            except RuntimeError as read_error:
                if "(NotFound)" in str(read_error):
                    return
                raise
            if current["metadata"]["uid"] != m["uid"]:
                raise RuntimeError(
                    "Resource replaced during cleanup; refusing deletion"
                ) from exc
            self.delete_owned(current, run_id, attempts - 1, guard)


class Run:
    def __init__(self, p, directory, run_id, cluster=None):
        if not re.fullmatch(r"kv-[0-9a-f]{16}", run_id):
            raise ValueError("Invalid run identity")
        self.p, self.directory, self.id = p, Path(directory), run_id
        self.c = cluster or Cluster(p)
        self.case = "preflight"
        self.results = []
        self.events = []
        self.uid = None
        self.namespaces = [p["namespace"]]
        self.started = time.monotonic()
        self.counter = 0
        self.job_uids = set()
        self.initial_workers = None
        self.initial_slots = None
        self.smoke_snapshot = None
        self.initial_volume_uids = None
        self.allocated_volumes = []

    def record(self, kind, **fields):
        event = {
            "time": datetime.now(timezone.utc).isoformat(),
            "elapsed": time.monotonic() - self.started,
            "case": self.case,
            "kind": kind,
            **fields,
        }
        self.events.append(event)
        with (self.directory / "events.jsonl").open("a") as f:
            f.write(json.dumps(event) + "\n")

    def state(self):
        save(self.directory / "profile.json", self.p)
        save(
            self.directory / "run.json",
            {
                "id": self.id,
                "cluster_uid": self.uid,
                "namespaces": self.namespaces,
                "profile": self.p,
                "initial_volume_uids": self.initial_volume_uids,
                "allocated_volumes": self.allocated_volumes,
                "source_sha256": {
                    name: hashlib.sha256(
                        (Path(__file__).parent / name).read_bytes()
                    ).hexdigest()
                    for name in ("core.py", "scenarios.py", "suite.py")
                },
            },
        )

    def slots(self, required=None):
        result = {}
        for slot, config in self.p["slots"].items():
            root = path(config["state"])
            if not root.is_dir():
                raise Blocked(f"Missing controller state: {root}")
            paused = (root / "maintenance").exists()
            result[slot] = {"paused": paused}
            for name in ("desired", "observed", "retirement", "cold-start"):
                f = root / (name + ".json")
                if f.exists():
                    result[slot][name] = read_json(f)
            if required and slot in required:
                if paused:
                    raise Blocked(f"{slot} is paused; operator resume required")
                for name in ("retirement", "cold-start"):
                    if result[slot].get(name, {}).get("phase") in (
                        "blocked",
                        "checking",
                        "shutdown-committed",
                        "creating",
                        "waking",
                    ):
                        raise Blocked(f"{slot} has an unfinished {name} operation")
        return result

    def workers(self):
        selector = ",".join(f"{k}={v}" for k, v in self.p["worker_selector"].items())
        nodes = self.c.get("nodes", selector=selector)
        identities = {v["provider_id"] for v in self.p["slots"].values()}
        for n in nodes:
            if n["spec"].get(
                "providerID"
            ) not in identities or "node-role.kubernetes.io/control-plane" in n[
                "metadata"
            ].get("labels", {}):
                raise Blocked("Worker selector includes an unexpected node identity")
        return nodes

    def preflight(self):
        self.uid = self.c.identity()
        self.state()  # Persist identity before any possible mutation.
        self.c.get("namespace", self.p["namespace"])
        slots = self.slots([self.p["default_slot"]])
        self.initial_slots = slots
        nodes = self.workers()
        self.initial_workers = nodes
        queue = self.c.get("localqueues", self.p["queue"], self.p["namespace"])
        if queue["spec"]["clusterQueue"] != self.p["cluster_queue"]:
            raise Blocked("LocalQueue points to a different ClusterQueue")
        cq = self.c.get("clusterqueues", self.p["cluster_queue"])
        if not condition(cq, "Active"):
            raise Blocked("ClusterQueue is not Active")
        quota = {key: Decimal(0) for key in ("cpu", "memory", "ephemeral-storage")}
        for group in cq["spec"]["resourceGroups"]:
            for flavor in group["flavors"]:
                for resource in flavor["resources"]:
                    key = resource["name"]
                    if key in quota:
                        quota[key] += quantity(resource["nominalQuota"])
                    if quantity(resource.get("borrowingLimit", 0)):
                        raise Blocked("Pilot suite requires non-borrowing quota")
        if cq["spec"].get("cohort"):
            raise Blocked("Pilot queue must not borrow from a cohort")
        if any(quota[k] != quantity(self.p["budgets"][k]) for k in quota):
            raise Blocked("Live queue quota differs from the reviewed profile budget")
        foreign = [
            w
            for w in self.c.get("workloads", namespace=self.p["namespace"])
            if not condition(w, "Finished")
            and w["metadata"].get("labels", {}).get(LABEL) != self.id
        ]
        if foreign:
            raise Blocked("Pilot namespace has active foreign queue demand")
        try:
            version = command([str(path(self.p["kube_burner"])), "version"])
        except FileNotFoundError as exc:
            raise Blocked(
                "Install pinned kube-burner with install-kube-burner.py"
            ) from exc
        if not re.search(r"\bv?" + re.escape(VERSION) + r"\b", version):
            raise Blocked(f"Install pinned kube-burner {VERSION}")
        self.record(
            "preflight",
            cluster_uid=self.uid,
            slots=slots,
            nodes=nodes,
            quota={k: str(v) for k, v in quota.items()},
        )

    def meta(self, suffix, namespace=None):
        return {
            "name": f"{self.id}-{suffix}",
            "namespace": namespace or self.p["namespace"],
            "labels": {LABEL: self.id, CASE: self.case},
        }

    def create(self, obj):
        self.c.identity(self.uid)
        m = obj["metadata"]
        if (
            m.get("labels", {}).get(LABEL) != self.id
            or m["namespace"] not in self.namespaces
        ):
            raise RuntimeError("Create is not owned by this run")
        if obj["kind"] == "PersistentVolumeClaim" and self.initial_volume_uids is None:
            raise RuntimeError(
                "Storage inventory must be journaled before creating a PVC"
            )
        self.record("submission", object=obj)
        created = json.loads(
            self.c.call("create", "-f", "-", "-o", "json", data=json.dumps(obj))
        )
        if created["kind"] == "Job":
            self.job_uids.add(created["metadata"]["uid"])
        return created

    def validate_claim(self, claim):
        if self.initial_volume_uids is None:
            raise RuntimeError(
                "No initial volume inventory; refusing PVC deletion or data access"
            )
        name = claim["spec"].get("volumeName")
        if not name:
            return None
        pv = self.c.get("persistentvolumes", name)
        if (
            pv["metadata"]["uid"] in self.initial_volume_uids
            or pv["spec"].get("claimRef", {}).get("uid") != claim["metadata"]["uid"]
            or pv["spec"].get("persistentVolumeReclaimPolicy") != "Delete"
        ):
            raise RuntimeError(
                "PVC binding is not a fresh disposable volume; preserving claim and data"
            )
        identity = {"name": name, "uid": pv["metadata"]["uid"]}
        if identity not in self.allocated_volumes:
            self.allocated_volumes.append(identity)
            self.state()
        return pv

    def delete(self, obj):
        guard = self.validate_claim if obj["kind"] == "PersistentVolumeClaim" else None
        self.c.delete_owned(obj, self.id, guard=guard)

    def sample(self):
        ns = self.p["namespace"]
        selector = f"{LABEL}={self.id}"
        snapshot = {
            r: self.c.get(r, namespace=ns, selector=selector)
            for r in ("jobs", "pods", "workloads")
        }
        snapshot["nodes"] = self.workers()
        # Include controller-generated Workloads even if the Kueue version does not copy labels.
        owners = {x["metadata"]["uid"] for x in snapshot["jobs"]}
        workloads = self.c.get("workloads", namespace=ns)
        self.job_uids.update(owners)
        snapshot["workloads"] = [
            w
            for w in workloads
            if w["metadata"].get("labels", {}).get(LABEL) == self.id
            or any(
                o["uid"] in self.job_uids
                for o in w["metadata"].get("ownerReferences", [])
            )
        ]
        uids = owners | {
            x["metadata"]["uid"] for r in ("pods", "workloads") for x in snapshot[r]
        }
        snapshot["events"] = [
            e
            for e in self.c.get("events", namespace=ns)
            if e.get("involvedObject", {}).get("uid") in uids
        ]
        self.record("observation", **snapshot)
        for job in snapshot["jobs"]:
            if condition(job, "Failed"):
                raise AssertionError(f"Job failed: {job['metadata']['name']}")
        return snapshot

    def wait(self, predicate, timeout, description):
        deadline = time.monotonic() + timeout
        while True:
            value = predicate()
            if value:
                return value
            if time.monotonic() >= deadline:
                raise TimeoutError(description)
            time.sleep(self.p["timeouts"]["poll"])

    def observe_for(self, seconds, assertion):
        deadline = time.monotonic() + seconds
        while True:
            assertion(self.sample())
            if time.monotonic() >= deadline:
                return
            time.sleep(self.p["timeouts"]["poll"])

    def cleanup(self):
        if not self.uid:
            return
        self.c.identity(self.uid)
        for ns in self.namespaces:
            for resource in RESOURCES:
                for obj in self.c.get(
                    resource, namespace=ns, selector=f"{LABEL}={self.id}"
                ):
                    self.delete(obj)

            def gone():
                return not any(
                    self.c.get(r, namespace=ns, selector=f"{LABEL}={self.id}")
                    for r in RESOURCES
                )

            self.wait(
                gone, self.p["timeouts"]["cleanup"], f"Cleanup did not finish in {ns}"
            )
        if self.allocated_volumes:
            expected = {v["uid"] for v in self.allocated_volumes}
            self.wait(
                lambda: not any(
                    pv["metadata"]["uid"] in expected
                    for pv in self.c.get("persistentvolumes")
                ),
                self.p["timeouts"]["cleanup"],
                "Disposable PV reclamation did not finish",
            )
        self.record("cleanup-complete")

    def execute(self, name, function):
        self.case = name
        start = time.monotonic()
        status, detail = "passed", "Assertions passed"
        try:
            function(self)
        except (Blocked, FileNotFoundError) as exc:
            status, detail = "blocked", str(exc)
        except (Exception, KeyboardInterrupt) as exc:
            status, detail = "failed", f"{type(exc).__name__}: {exc}"
            if isinstance(exc, KeyboardInterrupt):
                raise
        finally:
            self.results.append(
                {
                    "name": name,
                    "status": status,
                    "detail": detail,
                    "seconds": time.monotonic() - start,
                }
            )
            self.report()

    def report(self):
        incomplete = any(r["status"] in ("failed", "blocked") for r in self.results)
        report = {
            "run": self.id,
            "status": "incomplete" if incomplete else "passed",
            "results": self.results,
            "metrics": metrics(self.events),
            "metrics_by_scenario": {
                case: metrics([e for e in self.events if e.get("case") == case])
                for case in sorted(
                    {e["case"] for e in self.events if e["kind"] == "observation"}
                )
            },
            "resource_timings": resource_timings(self.events),
            "elapsed_seconds": time.monotonic() - self.started,
        }
        save(self.directory / "report.json", report)
        lines = [
            f"# Kubernetes validation {self.id}",
            "",
            f"Status: **{report['status']}**",
            "",
            "| Scenario | Result | Evidence / prerequisite |",
            "|---|---|---|",
        ]
        lines += [
            f"| {r['name']} | {r['status']} | {r['detail'].replace(chr(10), ' ').replace('|', '/')} |"
            for r in self.results
        ]
        lines += [
            "",
            "Timing distributions (seconds; polling observations, no performance gate):",
            "",
            "```json",
            json.dumps(report["metrics_by_scenario"] or report["metrics"], indent=2),
            "```",
            "",
            "Raw observations: events.jsonl. Kube-burner configurations and logs are retained alongside this report.",
        ]
        (self.directory / "report.md").write_text("\n".join(lines) + "\n")
        suite = ET.Element(
            "testsuite",
            name="kubernetes-validation",
            tests=str(len(self.results)),
            failures=str(sum(r["status"] == "failed" for r in self.results)),
            errors=str(sum(r["status"] == "blocked" for r in self.results)),
            skipped=str(sum(r["status"] == "deferred" for r in self.results)),
        )
        for r in self.results:
            case = ET.SubElement(
                suite, "testcase", name=r["name"], time=str(r.get("seconds", 0))
            )
            kind = {"failed": "failure", "blocked": "error", "deferred": "skipped"}.get(
                r["status"]
            )
            if kind:
                ET.SubElement(case, kind, message=r["detail"]).text = r["detail"]
        ET.ElementTree(suite).write(
            self.directory / "junit.xml", encoding="unicode", xml_declaration=True
        )
        return 1 if incomplete else 0


def metrics(events):
    first, samples = {}, {}
    for e in events:
        if e["kind"] != "observation":
            continue
        t = e["elapsed"]
        for r in ("jobs", "pods", "workloads", "nodes"):
            for obj in e.get(r, []):
                key = obj["metadata"]["uid"]
                info = first.setdefault(key, {"seen": t, "kind": r})
                states = {
                    "complete": condition(obj, "Complete"),
                    "admitted": condition(obj, "Admitted"),
                    "ready": ready(obj),
                }
                for state, yes in states.items():
                    if yes and state not in info:
                        info[state] = t
                        samples.setdefault(
                            r + "_" + state + "_from_first_seen", []
                        ).append(t - info["seen"])
    result = {}
    for key, values in samples.items():
        values.sort()
        result[key] = {
            "count": len(values),
            "min": values[0],
            "p50": values[math.ceil(0.5 * len(values)) - 1],
            "p95": values[math.ceil(0.95 * len(values)) - 1],
            "max": values[-1],
        }
    observations = [e for e in events if e["kind"] == "observation"]
    duration = (
        observations[-1]["elapsed"] - observations[0]["elapsed"]
        if len(observations) > 1
        else 0
    )
    completed = sum("complete" in x and x["kind"] == "jobs" for x in first.values())
    result["completed_jobs"] = completed
    result["jobs_per_second"] = completed / duration if duration else None
    server_samples = {}
    for item in resource_timings(events):
        if not item.get("created"):
            continue
        created = datetime.fromisoformat(item["created"].replace("Z", "+00:00"))
        for state in ("Ready", "Admitted", "Complete"):
            if item.get(state):
                observed = datetime.fromisoformat(item[state].replace("Z", "+00:00"))
                delta = (observed - created).total_seconds()
                if delta >= 0:
                    server_samples.setdefault(
                        item["kind"] + "_creation_to_" + state.lower(), []
                    ).append(delta)
    for key, values in server_samples.items():
        values.sort()
        result[key] = {
            "count": len(values),
            "min": values[0],
            "p50": values[math.ceil(0.5 * len(values)) - 1],
            "p95": values[math.ceil(0.95 * len(values)) - 1],
            "max": values[-1],
        }
    return result


def resource_timings(events):
    """Preserve server timestamps and placement, without claiming polling precision."""
    result = {}
    for event in events:
        if event["kind"] != "observation":
            continue
        for kind in ("jobs", "workloads", "pods", "nodes"):
            for obj in event.get(kind, []):
                meta = obj["metadata"]
                key = meta["uid"]
                item = result.setdefault(
                    key,
                    {
                        "kind": kind,
                        "name": meta.get("name"),
                        "uid": key,
                        "created": meta.get("creationTimestamp"),
                        "first_observed": event.get("time"),
                    },
                )
                item["last_observed"] = event.get("time")
                item["node"] = obj.get("spec", {}).get("nodeName")
                for c in obj.get("status", {}).get("conditions", []):
                    if c.get("status") == "True" and c["type"] in (
                        "Ready",
                        "Admitted",
                        "Complete",
                    ):
                        item[c["type"]] = c.get("lastTransitionTime")
                if obj.get("status", {}).get("completionTime"):
                    item["Complete"] = obj["status"]["completionTime"]
    return list(result.values())
