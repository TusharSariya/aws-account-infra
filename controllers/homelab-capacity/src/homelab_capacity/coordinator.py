"""Single-owner Ubuntu reconciler. Rollout starts read-only and fails closed."""

import argparse
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone

from .capacity import verify, verify_storage
from .config import INVENTORY, load
from .effective import effective
from .journal import Journal
from .kube import Kube
from .kueue import CHECK, CONTROLLER, admission_patch
from .lifecycle import Observation, State, complete, decide, observe_off
from .management import Management
from .platform import Platform
from .policy import DAEMONSETS, classify, done, housekeeping_jobs, owner


def condition(obj, name):
    return any(
        c.get("type") == name and c.get("status") == "True"
        for c in obj.get("status", {}).get("conditions", [])
    )


class Coordinator:
    def __init__(self, config, *, kube=None, management=None, journal=None):
        self.config = config
        self.kube = kube or Kube(config)
        self.management = management or Management(config)
        self.journal = journal or Journal(config["journal"])
        self.platform = Platform(self.kube, self.management, self.journal)
        self.states = {
            h: State(**self.journal.read(h + ".json", {})) for h in INVENTORY
        }
        for state in self.states.values():
            state.restart()

    def persist(self, host):
        self.journal.write(host + ".json", self.states[host].to_dict())

    def reconfigure(self, config):
        mutable = {"modes", "idle_seconds"}
        if {k: v for k, v in config.items() if k not in mutable} != {
            k: v for k, v in self.config.items() if k not in mutable
        }:
            raise RuntimeError(
                "Credential, inventory or budget changes require a service restart"
            )
        if (
            config.get("idle_seconds") != self.config.get("idle_seconds")
            or config["modes"] != self.config["modes"]
        ):
            for host, state in self.states.items():
                state.idle_since = None
                self.persist(host)
        self.config = config

    def command(self, host):
        request = self.journal.read(host + "-command.json")
        if not request:
            return
        seen = self.journal.read(host + "-command-result.json", {})
        if seen.get("id") == request["id"]:
            return
        state = self.states[host]
        action = request["action"]
        if action == "pause":
            state.paused = True
        elif action == "resume":
            state.paused = False
            if state.phase == "blocked":
                # Resume is explicit recovery; never assume an uncertain effect succeeded.
                record = self.journal.read(host + "-platform.json", {})
                state.phase = (
                    "restoring"
                    if record and record.get("phase") != "complete"
                    else "unknown"
                )
                state.pending = None
                state.deadline = None
            state.idle_since = None
        elif action == "wake":
            state.wake_requested = True
            state.shutdown_requested = False
        elif action == "shutdown":
            state.shutdown_requested = True
        else:
            raise ValueError("Unknown operator command")
        self.persist(host)
        self.journal.write(
            host + "-command-result.json", {"id": request["id"], "action": action}
        )

    def observation(self, host, objects):
        registration = INVENTORY[host]
        node = next(
            n for n in objects["nodes"] if n["metadata"]["name"] == registration["node"]
        )
        identity = (
            node["metadata"]["uid"] == registration["node_uid"]
            and node["status"]["nodeInfo"]["systemUUID"] == registration["system_uuid"]
        )
        power = self.management.power(host).get_power().power
        ai_pods = [
            p
            for p in objects["pods"]
            if p["metadata"]["namespace"] == "homelab-models"
            and p["metadata"].get("labels", {}).get("app") == "ai-runtime"
            and not done(p)
        ]
        ai_idle = False
        runtime = next(
            (
                d
                for d in objects["deployments"]
                if d["metadata"]["namespace"] == "homelab-models"
                and d["metadata"]["name"] == "ai-runtime"
            ),
            None,
        )
        if runtime:
            activity = json.loads(
                runtime["metadata"]
                .get("annotations", {})
                .get("homelab/lifecycle-state", "{}")
            )
            if not ai_pods:
                ai_idle = activity.get("desired") == "off"
            elif activity.get("desired") == "on" and not activity.get("tickets"):
                # Trust only the existing authenticated lifecycle observations tied
                # to current ready Pod UIDs. A stale/unknown source resets host idle.
                ids = {p["metadata"]["uid"] for p in ai_pods if condition(p, "Ready")}
                sources = activity.get("sources", {})
                ai_idle = all(
                    name in sources
                    and sources[name].get("known") is True
                    and sources[name].get("instance", "").split("|")[0] in ids
                    and 0 <= time.time() - sources[name].get("at", 0) <= 15
                    for name in ["ollama", "odysseus"]
                )
        demand, blockers = classify(host, objects, verified_ai_idle=ai_idle)
        from .kueue import unreserved_demand

        potential = {
            h: self.journal.read(h + "-capacity.json", {}).get("quotas", {})
            for h in INVENTORY
        }
        demand |= host in unreserved_demand(objects, potential)

        for gateway in self.config.get("gateways", []):
            if gateway["host"] != host:
                continue
            lease = next(
                (
                    o
                    for o in objects["leases"]
                    if o["metadata"]["namespace"] == gateway["namespace"]
                    and o["metadata"]["name"] == gateway["name"]
                ),
                None,
            )
            try:
                age = (
                    time.time()
                    - datetime.fromisoformat(lease["spec"]["renewTime"]).timestamp()
                )
                annotations = lease["metadata"]["annotations"]
                if not 0 <= age <= 30:
                    raise ValueError("Stale gateway")
                if not any(
                    p["metadata"]["namespace"] == gateway["namespace"]
                    and p["metadata"].get("labels", {}).get("app") == gateway["name"]
                    and p["metadata"]["uid"] == lease["spec"]["holderIdentity"]
                    and condition(p, "Ready")
                    and not p["metadata"].get("deletionTimestamp")
                    for p in objects["pods"]
                ):
                    raise ValueError(
                        "Gateway lease is not owned by its current ready Pod"
                    )
                active = int(annotations["homelab.tfdraw.dev/active"])
                if active < 0:
                    raise ValueError("Invalid activity")
                demand |= active > 0
            except (ValueError, KeyError, TypeError):
                blockers.append("Gateway activity unavailable: " + gateway["name"])
        holds = self.journal.read(host + "-holds.json", {})
        if holds:
            demand = True
            blockers.append("Operator/CI hold")
        for lease in objects["leases"]:
            meta = lease["metadata"]
            if (
                meta["namespace"] == "homelab-platform"
                and meta.get("labels", {}).get("homelab.tfdraw.dev/power-hold")
                == "true"
                and host
                in meta.get("annotations", {})
                .get("homelab.tfdraw.dev/hosts", "")
                .split(",")
            ):
                # Explicit release is required. A killed CI runner cannot silently
                # expire protection while its external infrastructure apply runs.
                demand = True
                blockers.append("Durable CI hold: " + meta["name"])
        record = self.journal.read(host + "-platform.json", {})
        quiesced = record.get("phase") == "quiesced"
        obs = Observation(
            power=power,
            identity_ok=identity,
            demand=demand,
            blockers=blockers,
            complete=True,
            quiesced=quiesced,
            retirement_ready=not (
                host == "primary" and (ai_pods or housekeeping_jobs(objects))
            ),
        )
        if power == "on":
            try:
                pve = self.management.pve(host)
            except (RuntimeError, TimeoutError, OSError):
                obs.complete = False
                obs.restore_ready = False
                obs.blockers.append("Proxmox not observable")
                return obs
            obs.vm_stopped = pve["status"] == "stopped"
            obs.host_empty = not pve["other_running"] and not pve["users"]
            obs.ready = condition(node, "Ready") and not node["spec"].get(
                "unschedulable", False
            )
            # Node readiness is only one restoration step. Keep invoking restore
            # until applications and schedules have also reached their saved state.
            obs.ready = obs.ready and (not record or record.get("phase") == "complete")
            if obs.ready:
                self.management.storage(host)
                budgets = self.config.get("capacity")
                if budgets:
                    if budgets["pool"].get("dynamic", False):
                        sample = effective(
                            node,
                            objects,
                            self.kube.stats(host),
                            record,
                            storage_headroom=budgets["pool"].get(
                                "storageHeadroom", "0"
                            ),
                        )
                        self.journal.write(host + "-capacity.json", sample)
                    else:
                        verify(
                            node,
                            objects["pods"],
                            budgets["pool"]["platformReserve"],
                            budgets["pool"],
                            expected_node=registration["node"],
                        )
                        verify_storage(
                            node,
                            objects["pods"],
                            self.kube.stats(host),
                            budgets["pool"],
                            budgets["catalog"],
                        )
                elif self.config.get("modes", {}).get(host, "observe") != "observe":
                    raise RuntimeError(
                        "Reviewed capacity budgets are required before admission"
                    )
                # Networking agents must actually be running on the selected node.
                for name in ["cilium", "kube-proxy"]:
                    if not any(
                        p["spec"].get("nodeName") == registration["node"]
                        and owner(p)
                        and owner(p)["name"] == name
                        and condition(p, "Ready")
                        for p in objects["pods"]
                    ):
                        obs.ready = False
            if quiesced:
                obs.quiesced = all(
                    done(p)
                    or (
                        owner(p)
                        and owner(p)["kind"] == "DaemonSet"
                        and (p["metadata"]["namespace"], owner(p)["name"]) in DAEMONSETS
                    )
                    for p in objects["pods"]
                    if p["spec"].get("nodeName") == registration["node"]
                )
        return obs

    def effect(self, host, action, objects):
        if action == "wake":
            self.management.power(host).ensure_on()
        elif action in {"restore", "cancel"}:
            pve = self.management.pve(host)
            if pve["status"] == "stopped":
                self.management.pve(host, "start-worker")
                return
            node = next(
                n
                for n in objects["nodes"]
                if n["metadata"]["name"] == INVENTORY[host]["node"]
            )
            if condition(node, "Ready"):
                self.platform.restore(host, objects)
        elif action == "quiesce":
            self.require_acceptance(host)
            self.platform.quiesce(host, objects)
        elif action == "stop-worker":
            self.require_acceptance(host)
            # A fresh observation after quiescing closes the submission race.
            fresh = self.observation(host, self.kube.inventory())
            if (
                fresh.demand
                or fresh.blockers
                or not fresh.complete
                or not fresh.retirement_ready
                or not fresh.quiesced
            ):
                raise RuntimeError("Demand/activity changed before shutdown commit")
            self.management.talos(host, "shutdown", "--wait=false")
        elif action == "stop-host":
            self.require_acceptance(host)
            self.management.pve(host, "poweroff")
        else:
            raise ValueError("Unsupported lifecycle effect")

    def require_acceptance(self, host):
        receipt = self.journal.read("acceptance.json", {})
        required = ["always_on", "dns", "capacity", "storage", "wake", "independence"]
        if not all(receipt.get(k) is True for k in required) or host not in receipt.get(
            "shutdown_hosts", []
        ):
            raise RuntimeError("Automatic shutdown acceptance is incomplete")

    def tick(self):
        try:
            objects = self.kube.inventory()
        except Exception:
            if self.config.get("capacity", {}).get("pool", {}).get("dynamic") and any(
                mode != "observe" for mode in self.config["modes"].values()
            ):
                from .kueue import reconcile_quotas

                reconcile_quotas(self.kube, {})
                for workload in self.kube.get("workloads.kueue.x-k8s.io")["items"]:
                    patch = admission_patch(workload, set())
                    if patch:
                        self.kube.patch(
                            "workloads.kueue.x-k8s.io", workload, patch, status=True
                        )
            raise
        seen = self.journal.read("gateway-activity.json", {})
        for gateway in self.config.get("gateways", []):
            key = gateway["namespace"] + "/" + gateway["name"]
            lease = next(
                (
                    o
                    for o in objects["leases"]
                    if o["metadata"]["namespace"] == gateway["namespace"]
                    and o["metadata"]["name"] == gateway["name"]
                ),
                None,
            )
            if lease:
                activity = float(
                    lease["metadata"]
                    .get("annotations", {})
                    .get("homelab.tfdraw.dev/last-activity", 0)
                )
                if activity > seen.get(key, 0) and (
                    key in seen or 0 <= time.time() - activity <= 30
                ):
                    self.states[gateway["host"]].wake_requested = True
                    self.persist(gateway["host"])
                seen[key] = activity
        self.journal.write("gateway-activity.json", seen)
        observed, ready = {}, set()
        for host in INVENTORY:
            self.command(host)
            state = self.states[host]
            try:
                obs = self.observation(host, objects)
                observed[host] = asdict(obs)
                observe_off(state, obs)
                action = decide(
                    state,
                    obs,
                    time.monotonic(),
                    mode=self.config["modes"][host],
                    idle_seconds=self.config.get("idle_seconds", 1800),
                )
                self.persist(host)  # write-ahead of every external effect
                if action:
                    try:
                        self.effect(host, action, objects)
                    except Exception as exc:  # noqa: BLE001 - fail closed at external-effect boundaries
                        complete(
                            state, action, error=type(exc).__name__ + ": " + str(exc)
                        )
                    else:
                        complete(state, action)
                    self.persist(host)
                if obs.ready and state.phase in {"ready", "idle"} and not state.paused:
                    ready.add(host)
                if state.phase == "blocked" and self.config["modes"][host] != "observe":
                    node = self.kube.get("nodes", INVENTORY[host]["node"])
                    annotations = node["metadata"].get("annotations", {}).copy()
                    if annotations.get("homelab.tfdraw.dev/power-intent") == "sleep":
                        annotations["homelab.tfdraw.dev/power-intent"] = "blocked"
                        self.kube.guarded(
                            "nodes",
                            node,
                            [
                                {
                                    "op": "add",
                                    "path": "/metadata/annotations",
                                    "value": annotations,
                                }
                            ],
                        )
            except Exception as exc:  # noqa: BLE001 - fail closed at external-effect boundaries
                state.idle_since = None
                state.reason = "Observation failed: " + type(exc).__name__
                self.persist(host)
        if self.config.get("capacity", {}).get("pool", {}).get("dynamic") and any(
            mode != "observe" for mode in self.config["modes"].values()
        ):
            from .kueue import reconcile_quotas

            budgets = {}
            for host in INVENTORY:
                sample = self.journal.read(host + "-capacity.json", {})
                fresh = (
                    host in ready
                    and 0 <= time.time() - sample.get("observed_at", 0) <= 30
                )
                if not fresh:
                    ready.discard(host)
                sleeping = observed.get(host, {}).get("power") == "off"
                budgets[host] = sample.get("quotas", {}) if fresh or sleeping else {}
            reconcile_quotas(self.kube, budgets)
        # Nexus must be healthy before primary counts as a CI dependency.
        nexus = next(
            (
                o
                for o in objects["deployments"]
                if o["metadata"]["namespace"] == "homelab-cache"
                and o["metadata"]["name"] == "nexus"
            ),
            None,
        )
        if not nexus or nexus.get("status", {}).get("availableReplicas", 0) < 1:
            ready.discard("primary")
        allowed = None
        if self.config.get("capacity", {}).get("pool", {}).get("dynamic"):
            from .kueue import admission_budget

            samples = {
                h: self.journal.read(h + "-capacity.json", {}).get("quotas", {})
                for h in ready
            }
            allowed = admission_budget(objects["workloads"], samples, ready)
        if any(mode != "observe" for mode in self.config["modes"].values()):
            check = self.kube.get("admissionchecks.kueue.x-k8s.io", CHECK)
            if check["spec"]["controllerName"] != CONTROLLER:
                raise RuntimeError("AdmissionCheck belongs to another controller")
            if not condition(check, "Active"):
                conditions = [
                    c
                    for c in check.get("status", {}).get("conditions", [])
                    if c["type"] != "Active"
                ]
                conditions.append(
                    {
                        "type": "Active",
                        "status": "True",
                        "reason": "Ready",
                        "message": "Retained-host coordinator is observing demand",
                        "lastTransitionTime": datetime.now(timezone.utc).isoformat(),
                        "observedGeneration": check["metadata"]["generation"],
                    }
                )
                operations = (
                    [
                        {
                            "op": "add",
                            "path": "/status",
                            "value": {"conditions": conditions},
                        }
                    ]
                    if "status" not in check
                    else [
                        {"op": "add", "path": "/status/conditions", "value": conditions}
                    ]
                )
                self.kube.guarded(
                    "admissionchecks.kueue.x-k8s.io", check, operations, status=True
                )
            for workload in objects["workloads"]:
                patch = admission_patch(
                    workload,
                    ready
                    if allowed is None or workload["metadata"]["uid"] in allowed
                    else set(),
                )
                if patch:
                    self.kube.patch(
                        "workloads.kueue.x-k8s.io", workload, patch, status=True
                    )
        self.journal.write(
            "observations.json",
            {
                "observed_at": time.time(),
                "hosts": observed,
                "admission_ready": sorted(ready),
            },
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    coordinator = Coordinator(load(args.config))
    with coordinator.journal.locked():
        while True:
            try:
                coordinator.reconfigure(load(args.config))
                coordinator.tick()
            except Exception as exc:  # noqa: BLE001 - fail closed at external-effect boundaries
                for host, state in coordinator.states.items():
                    state.idle_since = None
                    state.reason = "Reconciliation unavailable: " + type(exc).__name__
                    coordinator.persist(host)
                print(
                    json.dumps(
                        {"event": "reconcile-error", "type": type(exc).__name__}
                    ),
                    flush=True,
                )
            if args.once:
                break
            time.sleep(15)


if __name__ == "__main__":
    main()
