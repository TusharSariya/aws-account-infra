"""Manual, bounded pilot scenarios. No direct host or VM operations."""

import json
import os
import subprocess
import time

from core import (
    Blocked,
    CASE,
    LABEL,
    condition,
    command,
    path,
    quantity,
    read_json,
    ready,
    save,
)


def pod_spec(r, seconds=30, cpu=None, selector=None, script=None):
    load = r.p["load"]
    cpu = cpu or load["cpu"]
    selector = (
        selector if selector is not None else {r.p["slot_label"]: r.p["default_slot"]}
    )
    return {
        "schedulerName": r.p["scheduler"],
        "restartPolicy": "Never",
        "automountServiceAccountToken": False,
        "nodeSelector": {**r.p["worker_selector"], **selector},
        "securityContext": {
            "runAsNonRoot": True,
            "runAsUser": 1000,
            "runAsGroup": 1000,
            "fsGroup": 1000,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "containers": [
            {
                "name": "probe",
                "image": r.p["image"],
                "command": ["sh", "-ec", script or f"sleep {seconds}"],
                "resources": {
                    "requests": {
                        "cpu": cpu,
                        "memory": load["memory"],
                        "ephemeral-storage": load["scratch"],
                    },
                    "limits": {
                        "cpu": cpu,
                        "memory": load["memory"],
                        "ephemeral-storage": load["scratch"],
                    },
                },
                "securityContext": {
                    "readOnlyRootFilesystem": True,
                    "allowPrivilegeEscalation": False,
                    "capabilities": {"drop": ["ALL"]},
                },
            }
        ],
    }


def job(r, suffix, seconds=30, cpu=None, selector=None, script=None):
    metadata = r.meta(suffix)
    metadata["labels"]["kueue.x-k8s.io/queue-name"] = r.p["queue"]
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": metadata,
        "spec": {
            "suspend": True,
            "backoffLimit": 0,
            "template": {
                "metadata": {
                    "labels": {LABEL: r.id, CASE: r.case},
                    "annotations": {"prototype.homelab/policy": "on-invoke"},
                },
                "spec": pod_spec(r, seconds, cpu, selector, script),
            },
        },
    }


def owned_pods(snapshot, jobs):
    uids = {j["metadata"]["uid"] for j in jobs}
    return [
        p
        for p in snapshot["pods"]
        if any(o["uid"] in uids for o in p["metadata"].get("ownerReferences", []))
    ]


def admission(r, names, complete=True, generator=None):
    """Admission deadline only ticks while matching schedulable capacity is usable."""
    start = time.monotonic()
    usable_since = {}
    executing_since = {}
    capacity_seen = set()
    expected = set(names)

    def poll():
        if generator is not None and generator.poll() not in (None, 0):
            raise AssertionError("kube-burner generation failed; inspect the batch log")
        s = r.sample()
        now = time.monotonic()
        node_pods = {}
        cq = r.c.get("clusterqueues", r.p["cluster_queue"])
        quota_free = {
            k: quantity(r.p["budgets"][k])
            for k in ("cpu", "memory", "ephemeral-storage")
        }
        for flavor in cq.get("status", {}).get("flavorsReservation", []):
            for resource in flavor["resources"]:
                if resource["name"] in quota_free:
                    quota_free[resource["name"]] -= quantity(resource["total"])
        jobs = [j for j in s["jobs"] if j["metadata"]["name"] in expected]
        for j in jobs:
            name = j["metadata"]["name"]
            if condition(j, "Complete"):
                continue
            template = j["spec"]["template"]["spec"]
            selector = template.get("nodeSelector", {})
            request = template["containers"][0]["resources"]["requests"]
            candidates = [
                n
                for n in s["nodes"]
                if ready(n)
                and not n["spec"].get("unschedulable")
                and not any(
                    t.get("effect") in ("NoSchedule", "NoExecute")
                    for t in n["spec"].get("taints", [])
                )
                and all(
                    n["metadata"].get("labels", {}).get(k) == v
                    for k, v in selector.items()
                )
            ]
            if candidates:
                capacity_seen.add(name)
            usable = False
            free_by_node = {}
            # Account for all existing Pods, including system and foreign workloads.
            for node in candidates:
                node_name = node["metadata"]["name"]
                if node_name not in node_pods:
                    node_pods[node_name] = json.loads(
                        r.c.call(
                            "get",
                            "pods",
                            "-A",
                            "--field-selector",
                            "spec.nodeName=" + node_name,
                            "-o",
                            "json",
                        )
                    )["items"]
                pods = node_pods[node_name]
                free = {
                    k: quantity(node["status"]["allocatable"].get(k, 0))
                    for k in request
                }
                for p in pods:
                    if p.get("status", {}).get("phase") in ("Succeeded", "Failed"):
                        continue
                    for container in p["spec"].get("containers", []) + p["spec"].get(
                        "initContainers", []
                    ):
                        for k in free:
                            free[k] -= quantity(
                                container.get("resources", {})
                                .get("requests", {})
                                .get(k, 0)
                            )
                if all(free[k] >= quantity(v) for k, v in request.items()):
                    usable = True
                free_by_node[node_name] = {k: str(v) for k, v in free.items()}
            suspended = j["spec"].get("suspend", False)
            if complete and not suspended:
                executing_since.setdefault(name, now)
                if (
                    now - executing_since[name]
                    > r.p["load"]["job_seconds"] + r.p["timeouts"]["completion"]
                ):
                    raise TimeoutError(f"Job execution did not complete: {name}")
            reserved = any(
                condition(w, "QuotaReserved")
                and any(
                    o["uid"] == j["metadata"]["uid"]
                    for o in w["metadata"].get("ownerReferences", [])
                )
                for w in s["workloads"]
            )
            within_quota = reserved or all(
                quota_free[k] >= quantity(v) for k, v in request.items()
            )
            if suspended and usable and within_quota:
                if name not in usable_since:
                    r.record(
                        "admission-clock-start",
                        job=name,
                        free_by_node=free_by_node,
                        quota_reserved=reserved,
                        quota_free={k: str(v) for k, v in quota_free.items()},
                    )
                usable_since.setdefault(name, now)
                if now - usable_since[name] > r.p["timeouts"]["admission"]:
                    raise TimeoutError(f"Admission after usable capacity: {name}")
            else:
                usable_since.pop(name, None)
            if name not in capacity_seen and now - start > r.p["timeouts"]["capacity"]:
                raise TimeoutError(f"Capacity readiness: {name}")
        if len(jobs) != len(expected):
            return False
        return (
            s
            if all(
                condition(j, "Complete")
                if complete
                else not j["spec"].get("suspend", False)
                for j in jobs
            )
            else False
        )

    return r.wait(
        poll,
        r.p["timeouts"]["capacity"]
        + r.p["timeouts"]["admission"]
        + r.p["timeouts"]["completion"]
        + r.p["load"]["job_seconds"],
        "Jobs did not complete",
    )


def smoke(r):
    # Prefer an already Ready, unpaused worker; do not manufacture overflow prerequisites.
    slots = r.slots()
    existing = [
        n for n in r.workers() if ready(n) and not n["spec"].get("unschedulable")
    ]
    slot = r.p["default_slot"]
    for n in existing:
        candidate = n["metadata"]["labels"].get(r.p["slot_label"])
        if candidate in slots and not slots[candidate]["paused"]:
            slot = candidate
            break
    obj = r.create(
        job(
            r,
            "smoke",
            seconds=5,
            selector={r.p["slot_label"]: slot},
            script="nslookup kubernetes.default.svc.cluster.local; sleep 5",
        )
    )
    s = admission(r, [obj["metadata"]["name"]])
    pods = owned_pods(s, [obj])
    if not pods or not all(p["spec"].get("nodeName") for p in pods):
        raise AssertionError("Smoke Job has no observed worker placement")
    assert_placement(r, s, pods)
    r.smoke_snapshot = s


def assert_placement(r, s, pods):
    nodes = {n["metadata"]["name"]: n for n in s["nodes"]}
    for p in pods:
        if not p["spec"].get("nodeName"):
            continue
        n = nodes.get(p["spec"]["nodeName"])
        if not n or any(
            n["metadata"].get("labels", {}).get(k) != v
            for k, v in p["spec"].get("nodeSelector", {}).items()
        ):
            raise AssertionError("Pod violated its worker selector")


def cancel(r, obj):
    r.c.delete_owned(obj, r.id)
    name, ns = obj["metadata"]["name"], obj["metadata"]["namespace"]

    def released():
        s = r.sample()
        return (
            not any(j["metadata"]["name"] == name for j in s["jobs"])
            and not owned_pods(s, [obj])
            and not any(
                any(
                    o["uid"] == obj["metadata"]["uid"]
                    for o in w["metadata"].get("ownerReferences", [])
                )
                for w in s["workloads"]
            )
        )

    r.wait(
        released,
        r.p["timeouts"]["cleanup"],
        "Cancellation did not release Job, Pods and Workload",
    )
    r.record("cancelled", name=name, namespace=ns)


def queueing(r):
    # Long-lived requests fill nominal quota without changing the queue or oversizing a worker.
    count = int(quantity(r.p["budgets"]["cpu"]) / quantity(r.p["load"]["cpu"]))
    if count >= r.p["budgets"]["max_jobs"]:
        raise Blocked("Quota-fill plus waiting Job exceeds max_jobs")
    holders = [r.create(job(r, f"quota-{i}", seconds=600)) for i in range(count)]
    [o["metadata"]["name"] for o in holders]
    if len(holders) >= r.p["budgets"]["max_jobs"]:
        raise Blocked("Quota-fill plus waiting Job exceeds the max_jobs budget")

    # Kueue can reserve quota while provisioning; do not require all holders to run on one worker.
    def reserved():
        s = r.sample()
        return (
            s
            if len([w for w in s["workloads"] if condition(w, "QuotaReserved")])
            == len(holders)
            else False
        )

    r.wait(reserved, r.p["timeouts"]["capacity"], "Quota was not reserved")
    extra = r.create(job(r, "waiting", seconds=5))

    def waiting(s):
        j = next(
            j for j in s["jobs"] if j["metadata"]["name"] == extra["metadata"]["name"]
        )
        if not j["spec"].get("suspend") or owned_pods(s, [extra]):
            raise AssertionError("Excess demand ran before quota was released")

    r.observe_for(r.p["timeouts"]["negative"], waiting)
    # Cancel all holders so primary-only runs do not depend on paused secondary capacity.
    for holder in holders:
        current = r.c.get("jobs", holder["metadata"]["name"], r.p["namespace"])
        r.c.delete_owned(current, r.id)
    holder_uids = {j["metadata"]["uid"] for j in holders}

    def holders_released():
        s = r.sample()
        return (
            not any(j["metadata"]["uid"] in holder_uids for j in s["jobs"])
            and not owned_pods(s, holders)
            and not any(
                any(
                    o["uid"] in holder_uids
                    for o in w["metadata"].get("ownerReferences", [])
                )
                for w in s["workloads"]
            )
        )

    r.wait(
        holders_released,
        r.p["timeouts"]["cleanup"],
        "Cancelled quota holders did not release capacity",
    )
    r.record("cancelled", names=[j["metadata"]["name"] for j in holders])
    admission(r, [extra["metadata"]["name"]])
    followup = r.create(job(r, "released", seconds=5))
    admission(r, [followup["metadata"]["name"]])

    def quota_released():
        cq = r.c.get("clusterqueues", r.p["cluster_queue"])
        return all(
            quantity(x["total"]) == 0
            for f in cq.get("status", {}).get("flavorsReservation", [])
            for x in f["resources"]
        )

    r.wait(
        quota_released,
        r.p["timeouts"]["admission"],
        "Completed Jobs did not release queue reservations",
    )


def impossible(r):
    baseline = {n["metadata"]["uid"] for n in r.workers()}
    targets = {s: v.get("desired", {}).get("target") for s, v in r.slots().items()}
    cpu = str(quantity(r.p["budgets"]["cpu"]) + 1)
    objects = [
        r.create(job(r, "impossible", cpu=cpu)),
        r.create(
            job(
                r,
                "unsupported-selector",
                selector={
                    r.p["slot_label"]: r.p["default_slot"],
                    "validation.homelab.tfdraw.dev/unsupported": r.id,
                },
            )
        ),
    ]

    def check(s):
        for obj in objects:
            j = next(
                j for j in s["jobs"] if j["metadata"]["name"] == obj["metadata"]["name"]
            )
            if not j["spec"].get("suspend") or owned_pods(s, [obj]):
                raise AssertionError("Impossible Job ran")
        if {n["metadata"]["uid"] for n in s["nodes"]} - baseline:
            raise AssertionError("Impossible demand expanded worker capacity")
        if any(
            v.get("desired", {}).get("target", 0) > (targets[k] or 0)
            for k, v in r.slots().items()
        ):
            raise AssertionError("Impossible demand expanded provider target")

    r.observe_for(r.p["timeouts"]["negative"], check)


def require_two(r):
    r.slots(["primary", "secondary"])
    nodes = r.workers()
    if not all(
        any(
            n["spec"].get("providerID") == r.p["slots"][slot]["provider_id"]
            and ready(n)
            for n in nodes
        )
        for slot in r.p["slots"]
    ):
        raise Blocked("Two Ready workers required; suite does not unpause hosts")
    return nodes


def reuse(r):
    before = r.workers()
    ready_uids = {
        n["metadata"]["uid"]
        for n in before
        if ready(n) and not n["spec"].get("unschedulable")
    }
    if not ready_uids:
        raise Blocked("Reuse requires an existing Ready worker")
    targets = {s: v.get("desired", {}).get("target") for s, v in r.slots().items()}
    obj = r.create(job(r, "reuse", seconds=10))
    s = admission(r, [obj["metadata"]["name"]])
    pods = owned_pods(s, [obj])
    assert_placement(r, s, pods)
    placed = {p["spec"]["nodeName"] for p in pods}
    if not placed or any(
        n["metadata"]["uid"] not in ready_uids
        for n in s["nodes"]
        if n["metadata"]["name"] in placed
    ):
        raise AssertionError("Fitting work did not reuse existing capacity")
    if any(
        v.get("desired", {}).get("target", 0) > (targets[k] or 0)
        for k, v in r.slots().items()
    ):
        raise AssertionError("Fitting work caused expansion")


def packing(r):
    require_two(r)
    base = r.create(
        job(
            r,
            "busy",
            seconds=600,
            cpu="500m",
            selector={r.p["slot_label"]: "secondary"},
        )
    )
    admission(r, [base["metadata"]["name"]], complete=False)
    r.wait(
        lambda: any(ready(p) for p in owned_pods(r.sample(), [base])),
        120,
        "Busy worker seed did not become Ready",
    )
    probes = [
        r.create(job(r, f"pack-{i}", seconds=20, cpu="150m", selector={}))
        for i in range(2)
    ]
    s = admission(r, [p["metadata"]["name"] for p in probes])
    pods = owned_pods(s, probes)
    assert_placement(r, s, pods)
    secondary = next(
        n["metadata"]["name"]
        for n in s["nodes"]
        if n["spec"]["providerID"] == r.p["slots"]["secondary"]["provider_id"]
    )
    if len(pods) != 2 or any(p["spec"].get("nodeName") != secondary for p in pods):
        raise AssertionError("Small new requests were not packed on busy secondary")


def overflow(r):
    r.slots(["primary", "secondary"])
    nodes = r.workers()
    if (
        len(nodes) != 1
        or nodes[0]["spec"].get("providerID")
        != r.p["slots"]["secondary"]["provider_id"]
    ):
        raise Blocked(
            "Overflow proof starts with only Ready secondary; no forced worker deletion"
        )
    first = r.create(job(r, "fitting", seconds=600, cpu="1200m", selector={}))
    admission(r, [first["metadata"]["name"]], complete=False)
    r.wait(
        lambda: any(ready(p) for p in owned_pods(r.sample(), [first])),
        120,
        "First overflow holder did not run",
    )
    second = r.create(job(r, "overflow", seconds=20, cpu="1200m", selector={}))
    s = admission(r, [second["metadata"]["name"]])
    placements = {p["spec"].get("nodeName") for p in owned_pods(s, [first, second])}
    if len(placements) != 2 or len(s["nodes"]) != 2:
        raise AssertionError("Overflow did not expand to the second worker")


def from_zero(r):
    if r.initial_workers == [] and r.smoke_snapshot:
        if not r.initial_slots or any(
            not state["paused"] and state.get("desired", {}).get("target") != 0
            for state in r.initial_slots.values()
        ):
            raise Blocked(
                "Zero-worker proof requires zero initial targets on unpaused slots"
            )
        if not r.smoke_snapshot["nodes"] or not r.smoke_snapshot["pods"]:
            raise AssertionError("Zero-worker smoke did not observe fresh execution")
        r.record(
            "zero-worker-proof",
            evidence="Mandatory smoke started with no workers",
            snapshot=r.smoke_snapshot,
        )
        return
    if r.workers():
        raise Blocked(
            "Scale-from-zero requires no pilot workers at preflight; suite does not force retirement"
        )
    obj = r.create(job(r, "from-zero", seconds=10))
    s = admission(r, [obj["metadata"]["name"]])
    if not owned_pods(s, [obj]):
        raise AssertionError("No fresh worker execution observed")


def load_script(r):
    # Reserve bounded memory and scratch, and consume at most the cgroup CPU limit.
    # Disk page cache is charged to the same memory cgroup as tmpfs. Leave 25% headroom.
    memory_bytes = int(quantity(r.p["load"]["memory"]))
    scratch_kib = max(
        1,
        min(int(quantity(r.p["load"]["scratch"])) - 1024**2, memory_bytes // 2) // 1024,
    )
    memory_kib = max(1, memory_bytes // 4096)
    seconds = r.p["load"]["job_seconds"]
    return f"dd if=/dev/zero of=/scratch/data bs=1024 count={scratch_kib}; dd if=/dev/zero of=/memory/data bs=1024 count={memory_kib}; timeout {seconds} sh -c 'while :; do :; done' || test $? = 143"


def burner_config(r, count):
    r.counter += 1
    name = f"burst-{r.counter}"
    template = job(r, name + "-{{.Iteration}}", script=load_script(r))
    # Kube-burner labels the Job itself, but its Pod latency watcher selects Pods.
    template["spec"]["template"]["metadata"]["labels"]["kube-burner.io/runid"] = (
        "{{.RunID}}"
    )
    spec = template["spec"]["template"]["spec"]
    spec["volumes"] = [
        {"name": "scratch", "emptyDir": {"sizeLimit": r.p["load"]["scratch"]}},
        {
            "name": "memory",
            "emptyDir": {"medium": "Memory", "sizeLimit": r.p["load"]["memory"]},
        },
    ]
    spec["containers"][0]["volumeMounts"] = [
        {"name": "scratch", "mountPath": "/scratch"},
        {"name": "memory", "mountPath": "/memory"},
    ]
    filename = r.directory / (name + "-job.json")
    save(filename, template)
    config = {
        "global": {
            "gc": False,
            "waitWhenFinished": False,
            "timeout": f"{sum(r.p['timeouts'][k] for k in ('capacity', 'admission', 'completion')) + r.p['load']['job_seconds']}s",
            "measurements": [{"name": "podLatency"}],
        },
        "jobs": [
            {
                "name": name,
                "jobType": "create",
                "jobIterations": count,
                "namespace": r.p["namespace"],
                "namespacedIterations": False,
                "cleanup": False,
                "gc": False,
                "preLoadImages": False,
                "podWait": False,
                "waitWhenFinished": True,
                "maxWaitTimeout": f"{sum(r.p['timeouts'][k] for k in ('capacity', 'admission', 'completion')) + r.p['load']['job_seconds']}s",
                "qps": 4,
                "burst": 4,
                "objects": [{"objectTemplate": str(filename.resolve()), "replicas": 1}],
            }
        ],
    }
    cfg = r.directory / (name + ".json")
    save(cfg, config)
    return name, cfg


def burst(r, count):
    if not 0 < count <= r.p["budgets"]["max_jobs"]:
        raise ValueError("Burst exceeds max_jobs")
    r.slots([r.p["default_slot"]])
    r.c.identity(r.uid)
    name, cfg = burner_config(r, count)
    env = dict(os.environ, KUBECONFIG=str(path(r.p["kubeconfig"])))
    r.record("submission", batch=name, count=count)
    with (r.directory / (name + ".log")).open("w") as log:
        proc = subprocess.Popen(
            [
                str(path(r.p["kube_burner"])),
                "init",
                "-c",
                str(cfg.resolve()),
                "--uuid",
                r.id,
            ],
            cwd=r.directory,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            names = [f"{r.id}-{name}-{i}" for i in range(count)]
            admission(r, names, generator=proc)
            if proc.wait(timeout=60):
                raise AssertionError(f"kube-burner failed: see {name}.log")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)


def bursts(r):
    for count in r.p["load"]["bursts"]:
        burst(r, count)
        r.cleanup()


def sustained(r):
    original = r.p["load"]["job_seconds"]
    try:
        r.p["load"]["job_seconds"] = r.p["load"]["sustained_seconds"]
        burst(r, r.p["load"]["sustained_jobs"])
    finally:
        r.p["load"]["job_seconds"] = original


def services(r):
    backend = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": r.meta("backend"),
        "spec": pod_spec(
            r,
            script="mkdir -p /scratch/www; echo reachable > /scratch/www/index.html; httpd -f -p 8080 -h /scratch/www",
        ),
    }
    backend["spec"]["volumes"] = [
        {"name": "scratch", "emptyDir": {"sizeLimit": "64Mi"}}
    ]
    container = backend["spec"]["containers"][0]
    container["volumeMounts"] = [{"name": "scratch", "mountPath": "/scratch"}]
    container["readinessProbe"] = {
        "exec": {"command": ["test", "-f", "/scratch/ready"]},
        "periodSeconds": 2,
    }
    backend["metadata"]["labels"]["app"] = r.id + "-backend"
    b = r.create(backend)
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": r.meta("service"),
        "spec": {
            "selector": {"app": r.id + "-backend"},
            "ports": [{"port": 8080, "targetPort": 8080}],
        },
    }
    svc = r.create(service)
    r.wait(
        lambda: r.c.get("pods", b["metadata"]["name"], r.p["namespace"])
        .get("status", {})
        .get("phase")
        == "Running",
        900,
        "Backend not running",
    )

    def endpoints():
        return [
            e
            for s in r.c.get(
                "endpointslices",
                namespace=r.p["namespace"],
                selector="kubernetes.io/service-name=" + svc["metadata"]["name"],
            )
            for e in s.get("endpoints", [])
            if e.get("conditions", {}).get("ready")
        ]

    if endpoints():
        raise AssertionError("Unready backend published a Ready endpoint")
    r.c.call(
        "exec",
        "-n",
        r.p["namespace"],
        b["metadata"]["name"],
        "--",
        "touch",
        "/scratch/ready",
    )
    r.wait(endpoints, 120, "Ready endpoint missing")
    policy = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": r.meta("ingress"),
        "spec": {
            "podSelector": {"matchLabels": {"app": r.id + "-backend"}},
            "policyTypes": ["Ingress"],
            "ingress": [
                {
                    "from": [
                        {
                            "podSelector": {
                                "matchLabels": {LABEL: r.id, "access": "allowed"}
                            }
                        }
                    ],
                    "ports": [{"protocol": "TCP", "port": 8080}],
                }
            ],
        },
    }
    r.create(policy)
    for probe_name, mode in (
        ("allowed", "allowed"),
        ("denied", "denied"),
        ("allowed-after", "allowed"),
    ):
        # Test a known numeric backend endpoint too, so denied DNS cannot give a false positive.
        ip = r.c.get("pods", b["metadata"]["name"], r.p["namespace"])["status"]["podIP"]
        address = f"http://{ip}:8080"
        url = f"http://{svc['metadata']['name']}:8080"
        script = (
            f"nslookup kubernetes.default.svc.cluster.local; wget -T 5 -qO- {url}; wget -T 5 -qO- {address}"
            if mode == "allowed"
            else f"nslookup kubernetes.default.svc.cluster.local; for i in 1 2 3; do if wget -T 5 -qO- {address}; then exit 1; fi; sleep 2; done"
        )
        probe = job(r, probe_name, script=script)
        probe["spec"]["template"]["metadata"]["labels"]["access"] = mode
        obj = r.create(probe)
        admission(r, [obj["metadata"]["name"]])
    r.c.call(
        "exec",
        "-n",
        r.p["namespace"],
        b["metadata"]["name"],
        "--",
        "rm",
        "/scratch/ready",
    )
    r.wait(lambda: not endpoints(), 120, "Readiness loss did not withdraw endpoint")


def storage(r):
    config = r.p["storage"]
    if not config["class"]:
        raise Blocked(
            "Configure a disposable Delete StorageClass; existing Retain proof data is excluded"
        )
    slot = config["selector"].get(r.p["slot_label"])
    if slot:
        r.slots([slot])
    sc = r.c.get("storageclass", config["class"])
    if sc.get("reclaimPolicy") != "Delete":
        raise Blocked("Fresh PVC cleanup requires Delete reclaim policy")
    existing_volumes = r.c.get("persistentvolumes")
    if any(
        v.get("status", {}).get("phase") == "Available"
        and v["spec"].get("storageClassName") == config["class"]
        for v in existing_volumes
    ):
        raise Blocked(
            "Disposable class has pre-existing Available PVs; refusing possible data reuse"
        )
    r.initial_volume_uids = [v["metadata"]["uid"] for v in existing_volumes]
    r.state()  # Durable inventory precedes PVC creation, including interruption recovery.
    pvc = r.create(
        {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": r.meta("data"),
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": config["class"],
                "resources": {"requests": {"storage": config["size"]}},
            },
        }
    )
    claim = pvc["metadata"]["name"]
    volume_uid = None
    for i, script in enumerate(
        (
            None,
            f"test ! -e /data/marker; echo {r.id} > /data/marker; sync",
            f'test "$(cat /data/marker)" = {r.id}',
        )
    ):
        # A waiting consumer supports topology-aware binding but cannot write before identity checks.
        probe = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": r.meta(f"storage-{i}"),
            "spec": pod_spec(r, selector=config["selector"], script="sleep 1800"),
        }
        probe["spec"]["activeDeadlineSeconds"] = 1800
        probe["spec"]["volumes"] = [
            {"name": "data", "persistentVolumeClaim": {"claimName": claim}}
        ]
        probe["spec"]["containers"][0]["volumeMounts"] = [
            {"name": "data", "mountPath": "/data"}
        ]
        if script is None:
            # First consumer is read-only and cannot chown an unexpected pre-existing volume.
            del probe["spec"]["securityContext"]["fsGroup"]
            probe["spec"]["volumes"][0]["persistentVolumeClaim"]["readOnly"] = True
            probe["spec"]["containers"][0]["volumeMounts"][0]["readOnly"] = True
        obj = r.create(probe)

        def mounted():
            s = r.sample()
            current = next(
                p for p in s["pods"] if p["metadata"]["uid"] == obj["metadata"]["uid"]
            )
            assert_placement(r, s, [current])
            if current.get("status", {}).get("phase") == "Failed":
                raise AssertionError("Storage probe failed")
            return current if ready(current) else False

        current = r.wait(mounted, r.p["timeouts"]["capacity"], "Storage mount timeout")
        bound = r.c.get("persistentvolumeclaims", claim, r.p["namespace"])
        if bound["metadata"]["uid"] != pvc["metadata"]["uid"]:
            raise AssertionError("Test PVC identity changed")
        volume = r.validate_claim(bound)
        if volume is None or (volume_uid and volume["metadata"]["uid"] != volume_uid):
            raise AssertionError("Fresh test volume identity changed")
        volume_uid = volume["metadata"]["uid"]
        r.record("storage-binding", pvc=bound, pv=volume, pod=current)
        if script is not None:
            r.c.call(
                "exec",
                "-n",
                r.p["namespace"],
                current["metadata"]["name"],
                "--",
                "sh",
                "-ec",
                script,
            )
        r.delete(current)
        r.wait(
            lambda: not r.c.get(
                "pods", namespace=r.p["namespace"], selector=f"{LABEL}={r.id}"
            ),
            r.p["timeouts"]["cleanup"],
            "Storage Pod did not detach",
        )
    r.delete(bound)
    r.wait(
        lambda: not any(
            v["metadata"]["uid"] == volume_uid for v in r.c.get("persistentvolumes")
        ),
        r.p["timeouts"]["cleanup"],
        "Disposable volume cleanup did not complete",
    )


def controller(r, action, *args):
    if not path(r.p["controller"]).is_file():
        raise Blocked("Existing pilot consolidation controller is not installed")
    env = dict(
        os.environ,
        PYTHONPATH=str(path(r.p["controller_pythonpath"])),
        HOMELAB_IDLE_SECONDS=str(r.p["timeouts"]["idle"]),
    )
    return command(
        [path(r.p["controller_python"]), path(r.p["controller"]), action, *args],
        timeout=180,
        env=env,
    )


def idle_state(r):
    return read_json(r.p["idle_state"]).get("primary", {})


def lifecycle(r, cancellation=False):
    require_two(r)
    env = path(r.p["idle_env"])
    if (
        not env.exists()
        or f"HOMELAB_IDLE_SECONDS={r.p['timeouts']['idle']}"
        not in env.read_text().splitlines()
    ):
        raise Blocked("Installed idle window does not match profile")
    primary = next(
        n
        for n in r.workers()
        if n["spec"]["providerID"] == r.p["slots"]["primary"]["provider_id"]
    )
    before = read_json(path(r.p["slots"]["primary"]["state"]) / "observed.json")
    plan = json.loads(controller(r, "plan"))
    # plan output is inspected below by supported shape; never guess a controller decision.
    decision = plan.get("primary-to-secondary", plan)
    if not decision.get("allowed") or decision.get("moves"):
        raise Blocked(
            "Lifecycle needs an empty, eligible primary; no foreign applications may be moved"
        )
    controller(r, "apply", "--source", "primary", "--destination", "secondary")
    idle = r.wait(
        lambda: idle_state(r) if idle_state(r).get("phase") == "idle" else False,
        60,
        "Idle observation missing",
    )
    r.record("idle-start", state=idle, node=primary, observed=before)
    if cancellation:
        obj = r.create(job(r, "cancel-retirement", seconds=30))
        s = admission(r, [obj["metadata"]["name"]])
        current = next(
            n
            for n in s["nodes"]
            if n["spec"]["providerID"] == r.p["slots"]["primary"]["provider_id"]
        )
        if current["metadata"]["uid"] != primary["metadata"]["uid"] or current[
            "spec"
        ].get("unschedulable"):
            raise AssertionError("Returning demand failed to preserve/reopen worker")
        if idle_state(r).get("idleSince") is not None:
            raise AssertionError("Returning demand did not clear idle timer")
        r.record("retirement-cancelled", node=current)
        return
    started = idle["idleSince"]

    def retired():
        state = read_json(path(r.p["slots"]["primary"]["state"]) / "retirement.json")
        r.record("retirement-observation", state=state, idle=idle_state(r))
        return retirement_ready(
            state,
            primary["metadata"]["uid"],
            started,
            time.time(),
            r.p["timeouts"]["idle"],
        )

    r.wait(
        retired,
        r.p["timeouts"]["idle"] + r.p["timeouts"]["retirement_margin"],
        "Worker retirement timeout",
    )
    obj = r.create(job(r, "recreate", seconds=10))
    s = admission(r, [obj["metadata"]["name"]])
    current = next(
        n
        for n in s["nodes"]
        if n["spec"]["providerID"] == r.p["slots"]["primary"]["provider_id"]
    )
    assert_fresh_worker(primary, current)
    after = read_json(path(r.p["slots"]["primary"]["state"]) / "observed.json")
    r.record("worker-recreated", before=before, after=after, node=current)


SCENARIOS = {
    "smoke": smoke,
    "queueing": queueing,
    "impossible": impossible,
    "placement-reuse": reuse,
    "placement-packing": packing,
    "placement-overflow": overflow,
    "scale-from-zero": from_zero,
    "idle-recreation": lifecycle,
    "retirement-cancellation": lambda r: lifecycle(r, cancellation=True),
    "services": services,
    "storage": storage,
    "load-bursts": bursts,
    "load-sustained": sustained,
}


def consolidation(r):
    require_two(r)
    ns = r.p["consolidation_namespace"]
    if ns not in {n["metadata"]["name"] for n in r.c.get("namespaces")}:
        raise Blocked("Existing pilot consolidation namespace is required")
    r.namespaces.append(ns)
    r.state()
    if r.c.get("deployments", namespace=ns):
        raise Blocked("Consolidation namespace must have no foreign Deployments")
    seed = r.create(job(r, "pack-seed", seconds=600, cpu="500m"))
    admission(r, [seed["metadata"]["name"]], complete=False)
    r.wait(
        lambda: any(ready(p) for p in owned_pods(r.sample(), [seed])),
        120,
        "Consolidation seed not Ready",
    )
    spec = pod_spec(r, seconds=3600, cpu="500m", selector={})
    spec["restartPolicy"] = "Always"
    labels = {LABEL: r.id, CASE: r.case, "app": r.id}
    dep = r.create(
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": r.meta("move", ns),
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": r.id}},
                "template": {
                    "metadata": {
                        "labels": labels,
                        "annotations": {
                            "prototype.homelab/policy": "on-invoke",
                            "prototype.homelab/allow-move": "true",
                        },
                    },
                    "spec": spec,
                },
            },
        }
    )

    def pod():
        return next(
            (
                p
                for p in r.c.get("pods", namespace=ns, selector=f"{LABEL}={r.id}")
                if ready(p)
            ),
            None,
        )

    original = r.wait(pod, 120, "Consolidation Deployment not Ready")
    primary = next(
        n["metadata"]["name"]
        for n in r.workers()
        if n["spec"]["providerID"] == r.p["slots"]["primary"]["provider_id"]
    )
    if original["spec"]["nodeName"] != primary:
        raise Blocked(
            "Packing did not seed primary; suite does not cordon another host to force placement"
        )
    cancel(r, r.c.get("jobs", seed["metadata"]["name"], r.p["namespace"]))
    pdb = r.create(
        {
            "apiVersion": "policy/v1",
            "kind": "PodDisruptionBudget",
            "metadata": r.meta("protect", ns),
            "spec": {"minAvailable": 1, "selector": {"matchLabels": {"app": r.id}}},
        }
    )

    def decision():
        value = json.loads(controller(r, "plan"))
        allowed_uids = {
            p["metadata"]["uid"]
            for p in r.c.get("pods", namespace=ns, selector=f"{LABEL}={r.id}")
        }
        if any(m["uid"] not in allowed_uids for m in value.get("moves", [])):
            raise Blocked("Controller plan includes foreign workloads")
        r.record("consolidation-plan", plan=value)
        return value

    blocked = r.wait(
        lambda: (d if any(":pdb:" in b for b in d.get("blockers", [])) else False)
        if (d := decision())
        else False,
        60,
        "PDB blocker was not observed",
    )
    if blocked["allowed"]:
        raise AssertionError("PDB did not block movement")
    try:
        controller(r, "apply", "--source", "primary", "--destination", "secondary")
    except RuntimeError:
        pass
    else:
        raise AssertionError("Controller applied movement despite PDB")
    if pod()["metadata"]["uid"] != original["metadata"]["uid"]:
        raise AssertionError("PDB-blocked Pod was replaced")
    r.c.delete_owned(r.c.get("poddisruptionbudgets", pdb["metadata"]["name"], ns), r.id)
    # Apply policy only to this exact test Pod, with UID/RV checks.
    current = pod()
    patch = [
        {"op": "test", "path": "/metadata/uid", "value": current["metadata"]["uid"]},
        {
            "op": "test",
            "path": "/metadata/resourceVersion",
            "value": current["metadata"]["resourceVersion"],
        },
        {
            "op": "add",
            "path": "/metadata/annotations/prototype.homelab~1policy",
            "value": "persistent",
        },
    ]
    r.c.call(
        "patch",
        "pod",
        current["metadata"]["name"],
        "-n",
        ns,
        "--type=json",
        "-p",
        json.dumps(patch),
    )
    d = decision()
    if d["allowed"] or not any(b.endswith(":persistent") for b in d["blockers"]):
        raise AssertionError("Persistent workload policy did not block movement")
    current = pod()
    patch[1]["value"] = current["metadata"]["resourceVersion"]
    patch[2]["value"] = "on-invoke"
    r.c.call(
        "patch",
        "pod",
        current["metadata"]["name"],
        "-n",
        ns,
        "--type=json",
        "-p",
        json.dumps(patch),
    )
    r.wait(lambda: decision()["allowed"], 60, "Stateless movement is not eligible")
    controller(r, "apply", "--source", "primary", "--destination", "secondary")
    replacement = r.wait(
        lambda: (
            p if p and p["metadata"]["uid"] != original["metadata"]["uid"] else False
        )
        if (p := pod())
        else False,
        120,
        "No Ready replacement after movement",
    )
    if replacement["spec"]["nodeName"] == primary:
        raise AssertionError("Consolidation did not move application")
    r.record("consolidated", before=original, after=replacement, deployment=dep)
    # Demand uses the observer's existing cancellation interface to reopen primary.
    obj = r.create(job(r, "reopen", seconds=5))
    admission(r, [obj["metadata"]["name"]])


SCENARIOS["consolidation"] = consolidation


def assert_fresh_worker(before, after):
    if after["metadata"]["uid"] == before["metadata"]["uid"]:
        raise AssertionError("Disposable worker did not get a new node UID")
    old_uuid = before["status"]["nodeInfo"].get("systemUUID")
    new_uuid = after["status"]["nodeInfo"].get("systemUUID")
    if not old_uuid or not new_uuid or old_uuid.lower() == new_uuid.lower():
        raise AssertionError("Disposable worker hardware identity was not replaced")


def retirement_ready(state, uid, idle_since, now, idle_seconds):
    if state.get("phase") == "blocked":
        raise AssertionError("Lifecycle controller blocked retirement")
    if state.get("uid") == uid and state.get("phase") in (
        "shutdown-committed",
        "retired",
        "wake-requested",
    ):
        if now - idle_since < idle_seconds:
            raise AssertionError("Retirement occurred before configured idle window")
        return state
    return False
