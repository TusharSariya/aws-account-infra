"""Single-owner Ubuntu reconciler. Rollout starts read-only and fails closed."""

import argparse
import json
import socket
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .capacity import verify, verify_storage
from .config import INVENTORY, load
from .effective import effective
from .errors import RetryObservation, UncertainShutdown
from .interlock import Interlock, PowerBlocked
from .journal import Journal
from .kube import Kube
from .kueue import CHECK, CONTROLLER, admission_patch
from .lifecycle import (
    Observation,
    State,
    complete,
    decide,
    observe_off,
    recovery_expired,
)
from .mains import Mains
from .mains import mode as mains_mode
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
        self.imm_addresses = {}
        lock_dir = self.journal.directory
        if config.get("power_config"):
            power_config = json.loads(
                Path(config["power_config"]).expanduser().read_text()
            )
            lock_dir = power_config["lock_dir"]
            self.imm_addresses = {
                h: v["address"] for h, v in power_config["hosts"].items()
            }
        self.interlocks = {h: Interlock(lock_dir, h) for h in INVENTORY}
        self.mains = {
            h: Mains(entry, self.journal, h, self.interlocks[h])
            for h, entry in config.get("mains", {}).items()
            if entry.get("outlets") and entry.get("credentials_file")
        }
        for host, lock in self.interlocks.items():
            record = self.journal.read(host + "-mains.json", {})
            pending = lock.read()["pending"]
            if host not in self.mains and (
                record.get("phase") in {"cutting", "off", "energizing"}
                or (pending and pending["action"] in {"mains-on", "mains-off"})
            ):
                raise PowerBlocked("Keep mains configuration until recovery completes")
        self.platform = Platform(self.kube, self.management, self.journal)
        self.platform.interlocks = self.interlocks
        self.states = {
            h: State(**self.journal.read(h + ".json", {})) for h in INVENTORY
        }
        for state in self.states.values():
            state.restart()

    def milestone(self, host, phase, *, reset=False, at=None):
        name = host + "-startup.json"
        record = {} if reset else self.journal.read(name, {})
        record.setdefault(phase, time.time() if at is None else at)
        self.journal.write(name, record)

    def poll_interval(self):
        return (
            5
            if any(
                s.phase in {"waking", "restoring"} or s.wake_requested
                for s in self.states.values()
            )
            else 15
        )

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
            if self.interlocks[host].read()["pending"]:
                state.reason = "Resume cannot clear an unresolved external command"
                self.persist(host)
                self.journal.write(
                    host + "-command-result.json",
                    {"id": request["id"], "action": action, "rejected": state.reason},
                )
                return
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
        elif action == "commission-mains":
            try:
                if host not in self.mains:
                    raise PowerBlocked("Configure mains before commissioning")
                self.mains[host].start_commission()
                state.mains_commissioning = True
                state.wake_requested = True
            except (RuntimeError, ValueError) as exc:
                self.journal.write(
                    host + "-command-result.json",
                    {"id": request["id"], "action": action, "rejected": str(exc)},
                )
                return
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
        mains = self.mains.get(host)
        mains_state, cloud_healthy, mains_reason = "on", True, ""
        mains_record = mains.read() if mains else {}
        imm_available = None
        if mains and host in self.imm_addresses:
            try:
                with socket.create_connection((self.imm_addresses[host], 443), 2):
                    pass
            except OSError:
                imm_available = False
        power = "unknown"
        if imm_available is not False:
            try:
                power = self.management.power(host).get_power().power
                imm_available = True
            except (RuntimeError, OSError):
                if not mains:
                    raise
        if mains:
            try:
                mains_state = mains.observe(imm_available=imm_available)
            except PowerBlocked:
                raise
            except (RuntimeError, OSError, ValueError, KeyError):
                cloud_healthy = False
                mains_reason = "SmartThings unavailable; mains changes inhibited"
                mains_state = "on" if imm_available is True else "unknown"
            mains_record = mains.read()
            if (
                cloud_healthy
                and imm_available is False
                and (
                    (mains_state == "off" and mains_record["phase"] == "off")
                    or mains_record["phase"] == "energizing"
                )
            ):
                power = "off"
        cut_allowed = False
        if mains and cloud_healthy:
            try:
                mains.may_cut()
                cut_allowed = True
            except (RuntimeError, OSError, ValueError):
                mains_reason = (
                    "Mains removal not commissioned or authorization unhealthy"
                )
        lock = self.interlocks[host]
        if power == "on":
            lock.settle("imm-on")
            pending = lock.read()["pending"]
            if (
                mains
                and mains_record.get("shutdown")
                and self.states[host].phase != "stopping"
                and not pending
            ):
                mains.invalidate_shutdown()
        elif power == "off" and mains_state == "on":
            lock.settle("stop-host")
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
            maintenance=bool(lock.read()["holds"]),
            mains=mains_state,
            mains_retire=(mains.eligible(power, time.monotonic()) and cut_allowed)
            if mains
            else False,
            mains_reason=mains_reason,
            cloud_healthy=cloud_healthy,
            mains_transition=bool(
                mains
                and (mains_state != "on" or mains_record.get("phase") == "energizing")
            ),
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
                if mains:
                    obs.restore_mains = mains.commission_tick(self.states[host], obs)
                return obs
            self.milestone(host, "proxmox_available")
            obs.vm_stopped = pve["status"] == "stopped"
            obs.host_empty = not pve["other_running"] and not pve["users"]
            if pve.get("active_tasks") != []:
                obs.host_empty = False
                obs.blockers.append("Proxmox tasks active or unobservable")
            if obs.vm_stopped:
                lock.settle("stop-worker")
            elif pve["status"] == "running":
                lock.settle("start-worker")
            obs.ready = condition(node, "Ready") and not node["spec"].get(
                "unschedulable", False
            )
            if obs.ready:
                self.milestone(host, "talos_ready")
            # Node readiness is only one restoration step. Keep invoking restore
            # until applications and schedules have also reached their saved state.
            obs.ready = obs.ready and (not record or record.get("phase") == "complete")
            if obs.ready:
                self.milestone(host, "platform_restored")
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
        if mains:
            obs.restore_mains = mains.commission_tick(self.states[host], obs)
            obs.restore_mains |= mains_mode(
                mains.entry
            ) == "disabled" and mains_record.get("phase") in {"off", "energizing"}
        return obs

    def effect(self, host, action, objects):
        # Quiesce acquires protection separately for each application stage.
        if action == "quiesce":
            self.require_acceptance(host)
            return self.platform.quiesce(host, objects)
        with self.interlocks[host].guard():
            return self._effect(host, action, objects)

    def _effect(self, host, action, objects):
        if action in {"mains-on", "mains-off"}:
            if action == "mains-off":
                self.require_mains_acceptance(host)
                fresh = self.observation(host, self.kube.inventory())
                if (
                    fresh.power != "off"
                    or not fresh.mains_retire
                    or fresh.demand
                    or self.states[host].wake_requested
                    or fresh.blockers
                    or not fresh.complete
                    or fresh.maintenance
                ):
                    return "cancel"
            self.mains[host].advance("on" if action == "mains-on" else "off")
        elif action == "wake":
            if host in self.mains:
                self.mains[host].invalidate_shutdown()
            self.milestone(host, "demand_detected", reset=True)
            self.milestone(host, "power_on_request")
            self.management.power(host).ensure_on()
        elif action in {"restore", "cancel"}:
            pve = self.management.pve(host)
            if pve["status"] == "stopped":
                self.interlocks[host].begin("start-worker")
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
                return "cancel"
            self.interlocks[host].begin("stop-worker")
            self.management.talos(host, "shutdown", "--wait=false")
        elif action == "stop-host":
            self.require_acceptance(host)
            fresh = self.observation(host, self.kube.inventory())
            if (
                not (fresh.vm_stopped and fresh.host_empty and fresh.complete)
                or fresh.blockers
            ):
                raise PowerBlocked("Host shutdown preflight is blocked")
            self.interlocks[host].begin("stop-host")
            if host in self.mains:
                self.mains[host].shutdown_started(
                    self.interlocks[host].read()["pending"]["id"]
                )
            self.management.pve(host, "poweroff")
            if host in self.mains:
                self.mains[host].shutdown_acknowledged()
        else:
            raise ValueError("Unsupported lifecycle effect")

    def require_mains_acceptance(self, host):
        self.require_acceptance(host)
        self.mains[host].may_cut()

    def reconcile_protection(self, host, objects, obs):
        lock = self.interlocks[host]
        pending = lock.read()["pending"]
        if (
            pending
            and pending["action"] == "platform-stage"
            and self.platform.stage_settled(host, objects, pending)
        ):
            lock.settle("platform-stage")
        # Do not acknowledge while a Kubernetes mutation or guest transition is unresolved.
        state = self.states[host]
        pods = [
            p
            for p in objects["pods"]
            if p.get("spec", {}).get("nodeName") == INVENTORY[host]["node"]
        ]
        settled = (
            (obs.ready or (obs.power == "off" and obs.mains == "on"))
            and state.pending is None
            and not any(p["metadata"].get("deletionTimestamp") for p in pods)
        )
        if state.phase in {"restoring", "waking"}:
            settled = settled and all(done(p) or condition(p, "Ready") for p in pods)
        lock.acknowledge(settled=settled)
        for lease in objects.get("leases", []):
            meta = lease["metadata"]
            token = "ci-freeze-" + meta["uid"]
            held = lock.read()["holds"].get(token)
            if held and held["acknowledged"]:
                key = "homelab.tfdraw.dev/frozen-" + host
                if meta.get("annotations", {}).get(key) != meta["uid"]:
                    self.kube.guarded(
                        "leases",
                        lease,
                        [
                            {
                                "op": "add",
                                "path": "/metadata/annotations/"
                                + key.replace("/", "~1"),
                                "value": meta["uid"],
                            }
                        ],
                    )

    def require_acceptance(self, host):
        receipt = self.journal.read("acceptance.json", {})
        required = ["always_on", "dns", "capacity", "storage", "wake", "independence"]
        if not all(receipt.get(k) is True for k in required) or host not in receipt.get(
            "shutdown_hosts", []
        ):
            raise RuntimeError("Automatic shutdown acceptance is incomplete")

    def tick(self):
        for host, state in self.states.items():
            recovery_expired(state, time.monotonic())
            self.persist(host)
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
        for lease in objects.get("leases", []):
            meta = lease["metadata"]
            if (
                meta.get("namespace") != "homelab-platform"
                or meta.get("annotations", {}).get("homelab.tfdraw.dev/hold-mode")
                != "freeze"
            ):
                continue
            token = "ci-freeze-" + meta["uid"]
            for host in (
                meta["annotations"].get("homelab.tfdraw.dev/hosts", "").split(",")
            ):
                if host not in self.interlocks:
                    continue
                lock = self.interlocks[host]
                if (
                    meta.get("labels", {}).get("homelab.tfdraw.dev/power-hold")
                    == "true"
                ):
                    lock.acquire(token, "Critical CI operation: " + meta["name"])
                elif (
                    meta.get("labels", {}).get("homelab.tfdraw.dev/power-hold")
                    == "false"
                    and token in lock.read()["holds"]
                ):
                    lock.release(token)
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
                self.reconcile_protection(host, objects, obs)
                protected = self.interlocks[host].read()
                obs.maintenance = bool(protected["holds"] or protected["pending"])
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
                        outcome = self.effect(host, action, objects)
                    except PowerBlocked as exc:
                        state.pending = None
                        state.reason = str(exc)
                        outcome = None
                    except RetryObservation as exc:
                        complete(state, action, retry=str(exc))
                    except UncertainShutdown as exc:
                        # Once a shutdown write may have reached the host, only
                        # observations may advance it. Never turn this into retry.
                        complete(state, action)
                        state.reason = str(exc)
                    except Exception as exc:  # noqa: BLE001 - fail closed at external-effect boundaries
                        complete(
                            state, action, error=type(exc).__name__ + ": " + str(exc)
                        )
                    else:
                        complete(state, action, outcome=outcome)
                    self.persist(host)
                    event = {
                        "event": "power-transition",
                        "host": host,
                        "operation": state.operation,
                        "action": action,
                        "phase": state.phase,
                        "pending": state.pending,
                        "reason": state.reason,
                        "at": time.time(),
                    }
                    self.journal.write(host + "-transition.json", event)
                    print(json.dumps(event), flush=True)
                if (
                    obs.ready
                    and state.phase in {"ready", "idle"}
                    and not state.paused
                    and not obs.maintenance
                ):
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
                if host in self.mains:
                    self.mains[host].off_since = self.mains[host].last_off_sample = None
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
        elif "primary" in ready:
            self.milestone("primary", "nexus_ready")
        for workload in objects["workloads"]:
            if any(
                c["type"] == "Admitted" and c["status"] == "True"
                for c in workload.get("status", {}).get("conditions", [])
            ):
                from .kueue import assigned_hosts

                for host in assigned_hosts(workload):
                    self.milestone(host, "kueue_admitted")
        for pod in objects["pods"]:
            if pod["metadata"].get("namespace") == "arc-runners" and condition(
                pod, "Ready"
            ):
                for host, entry in INVENTORY.items():
                    if pod["spec"].get("nodeName") == entry["node"]:
                        self.milestone(host, "runner_pod_ready")
                        parent = owner(pod)
                        if parent and any(
                            r["metadata"]["uid"] == parent.get("uid")
                            and r.get("status", {}).get("ready") is True
                            for r in objects.get("runners", [])
                        ):
                            self.milestone(host, "runner_registered")
                        statuses = pod.get("status", {}).get("containerStatuses", [])
                        for status in statuses:
                            if status["name"] == "runner" and status.get(
                                "state", {}
                            ).get("running", {}).get("startedAt"):
                                self.milestone(
                                    host,
                                    "runner_container_started",
                                    at=datetime.fromisoformat(
                                        status["state"]["running"]["startedAt"]
                                    ).timestamp(),
                                )
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
                        "lastTransitionTime": datetime.now(UTC).isoformat(),
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
            time.sleep(coordinator.poll_interval())


if __name__ == "__main__":
    main()
