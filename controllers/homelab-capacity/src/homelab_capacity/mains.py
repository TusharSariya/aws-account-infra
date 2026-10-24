"""Outlet groups with durable intent and no replay of uncertain cloud writes."""

import time

from .interlock import PowerBlocked
from .smartthings import SmartThings


def mode(entry):
    return entry.get("mode", "automatic" if entry.get("enabled") else "disabled")


def validate(config):
    used = set()
    for host, entry in config.get("mains", {}).items():
        if (
            host not in {"primary", "secondary"}
            or type(entry.get("enabled", False)) is not bool
            or type(entry.get("allow_temporary_credentials", False)) is not bool
            or mode(entry) not in {"disabled", "commissioning", "automatic"}
        ):
            raise ValueError("Invalid mains host or enable flag")
        outlets = entry.get("outlets", [])
        for outlet in outlets:
            key = (outlet["device_id"], outlet["component_id"])
            if not all(isinstance(v, str) and v.strip() for v in key) or key in used:
                raise ValueError(
                    "Outlet IDs must be nonempty and exclusive to one host"
                )
            used.add(key)
        if mode(entry) != "disabled" and (
            not outlets or not entry.get("credentials_file")
        ):
            raise ValueError("Enabled mains control requires outlets and credentials")


class Mains:
    def __init__(
        self, entry, journal, host, interlock, *, adapter=None, clock=time.time
    ):
        self.entry, self.journal, self.host = entry, journal, host
        self.interlock, self.clock = interlock, clock
        self.adapter = adapter or SmartThings(entry["credentials_file"])
        self.name = host + "-mains.json"
        pending = self.interlock.read()["pending"]
        if (
            pending
            and pending.get("outlets")
            and pending["outlets"] != entry["outlets"]
        ):
            raise PowerBlocked("Outlet mapping changed during an unresolved command")
        self.samples = []
        self.off_since = None
        self.last_off_sample = None

    def read(self):
        return self.journal.read(self.name, {"phase": "unknown", "shutdown": None})

    def observe(self, *, imm_available=None):
        self.samples = [self.adapter.status(o) for o in self.entry["outlets"]]
        with self.interlock.locked():
            pending = self.interlock.read()["pending"]
            if pending and pending["action"] in {"mains-on", "mains-off"}:
                # Completion must be newer than intent, not just a cached matching state.
                if pending["outlets"] != self.entry["outlets"]:
                    raise PowerBlocked(
                        "Outlet mapping changed during an unresolved command"
                    )
                sample = self.samples[pending["index"]]
                if (
                    sample["state"] == pending["target"]
                    and sample["changed_at"] >= pending["at"]
                ):
                    final_outlet = all(
                        s["state"] == pending["target"] for s in self.samples
                    )
                    physical = (
                        imm_available is False
                        if pending["target"] == "off"
                        else imm_available is True
                    )
                    if not final_outlet or physical:
                        self.interlock.settle(pending["action"])
            values = {s["state"] for s in self.samples}
            state = next(iter(values)) if len(values) == 1 else "mixed"
            record = self.read()
            if record["phase"] == "off" and state != "off":
                raise PowerBlocked(
                    "Unexpected outlet change after mains-off; inspect before recovery"
                )
            if not self.interlock.read()["pending"]:
                if (
                    state == "off"
                    and record["phase"] == "cutting"
                    and imm_available is False
                ):
                    record["phase"] = "off"
                elif (
                    state == "on"
                    and record["phase"] == "energizing"
                    and imm_available is True
                ):
                    record.update(phase="standby", shutdown=None)
            record.update(state=state, observed_at=self.clock(), outlets=self.samples)
            self.journal.write(self.name, record)
            return state

    def session(self):
        return self.journal.read(self.host + "-commission.json", {})

    def start_commission(self):
        with self.interlock.guard():
            if mode(self.entry) != "commissioning":
                raise PowerBlocked(
                    "Select commissioning mode before requesting a cycle"
                )
            previous = self.session()
            if previous.get("stage") not in {None, "complete", "expired"}:
                raise PowerBlocked("Existing commissioning session requires recovery")
            proof = self.journal.read(self.host + "-mains-mapping.json", {})
            if (
                proof.get("host") != self.host
                or proof.get("outlets") != self.entry["outlets"]
                or not proof.get("evidence")
            ):
                raise PowerBlocked("Verified mapping evidence is required")
            if self.adapter.health()["remaining_seconds"] < 7200:
                raise PowerBlocked(
                    "Commissioning needs at least two hours of authorization"
                )
            import uuid

            record = {
                "id": str(uuid.uuid4()),
                "host": self.host,
                "outlets": self.entry["outlets"],
                "started_at": self.clock(),
                "expires_at": self.clock() + 5400,
                "stage": "preparing",
            }
            self.journal.write(self.host + "-commission.json", record)

    def commissioning(self):
        record = self.session()
        return (
            mode(self.entry) == "commissioning"
            and record.get("outlets") == self.entry["outlets"]
            and record.get("stage") in {"preparing", "idle", "waking"}
            and self.clock() < record.get("expires_at", 0)
        )

    def may_cut(self):
        auth = self.adapter.health()
        if auth["remaining_seconds"] < 3600 or auth["refresh_uncertain"]:
            raise PowerBlocked(
                "Authorization unhealthy or too close to expiry for mains removal"
            )
        if self.commissioning() and self.session()["stage"] == "idle":
            return
        if mode(self.entry) != "automatic":
            raise PowerBlocked("Automatic mains removal is disabled")
        if not (auth["renewable"] and auth["refresh_verified"]) and not self.entry.get(
            "allow_temporary_credentials", False
        ):
            raise PowerBlocked(
                "Verified renewable OAuth required for automatic mains removal"
            )
        receipt = self.journal.read(self.host + "-mains-acceptance.json", {})
        if (
            receipt.get("host") != self.host
            or receipt.get("outlets") != self.entry["outlets"]
            or not receipt.get("cycle_id")
        ):
            raise PowerBlocked("Complete cold-cycle evidence required")
        site = self.journal.read(self.host + "-mains-site.json", {})
        checks = ("electrical_rating", "exclusive_load", "no_competing_automation")
        if site.get("outlets") != self.entry["outlets"] or not all(
            site.get(k, {}).get("evidence") and site[k].get("checked_at")
            for k in checks
        ):
            raise PowerBlocked("Site review evidence is incomplete")

    def commission_tick(self, state, obs):
        record = self.session()
        if not record or record["stage"] == "complete":
            return False
        if record["outlets"] != self.entry["outlets"]:
            raise PowerBlocked("Commissioning mapping changed")
        if self.clock() >= record["expires_at"] or mode(self.entry) == "disabled":
            record["stage"] = "expired"
        if record["stage"] == "preparing":
            if obs.ready:
                record["stage"] = "idle"
                record["ready_before"] = self.clock()
                state.wake_requested = False
                state.shutdown_requested = False
            else:
                state.wake_requested = True
        elif record["stage"] == "idle" and self.read()["phase"] == "off":
            record["stage"] = "waking"
            record["mains_off_at"] = self.clock()
            record["shutdown_operation"] = self.read().get("shutdown")
            state.wake_requested = True
        elif record["stage"] == "waking":
            state.wake_requested = True
            if obs.ready and self.read()["phase"] == "standby":
                record.update(stage="complete", restored_at=self.clock())
                state.wake_requested = False
                state.mains_commissioning = False
                self.journal.write(
                    self.host + "-mains-acceptance.json",
                    {
                        "host": self.host,
                        "outlets": self.entry["outlets"],
                        "cycle_id": record["id"],
                        "shutdown_operation": record["shutdown_operation"],
                        "ready_before": record["ready_before"],
                        "mains_off_at": record["mains_off_at"],
                        "restored_at": record["restored_at"],
                    },
                )
        self.journal.write(self.host + "-commission.json", record)
        return record["stage"] == "expired" and obs.mains in {"off", "mixed"}

    def invalidate_shutdown(self):
        record = self.read()
        record.update(shutdown=None, shutdown_acknowledged=False, phase="standby")
        self.journal.write(self.name, record)
        self.off_since = self.last_off_sample = None

    def shutdown_started(self, operation):
        record = self.read()
        record.update(
            shutdown=operation, shutdown_acknowledged=False, phase="awaiting-host-off"
        )
        self.journal.write(self.name, record)

    def shutdown_acknowledged(self):
        record = self.read()
        record["shutdown_acknowledged"] = True
        self.journal.write(self.name, record)

    def eligible(self, power, now):
        record = self.read()
        if (
            power != "off"
            or not record.get("shutdown_acknowledged")
            or record["phase"] not in {"awaiting-host-off", "cutting"}
        ):
            self.off_since = self.last_off_sample = None
            return False
        if (
            self.last_off_sample is None
            or now - self.last_off_sample > 60
            or now < self.last_off_sample
        ):
            self.off_since = now
        self.last_off_sample = now
        return now - self.off_since >= 60

    def advance(self, target):
        with self.interlock.guard():
            if target not in {"on", "off"}:
                raise ValueError("Invalid mains target")
            record = self.read()
            if target == "off" and not record.get("shutdown_acknowledged"):
                raise PowerBlocked("No coordinator shutdown evidence")
            # Fresh preflight and one outstanding write across the entire PSU group.
            samples = [self.adapter.status(o) for o in self.entry["outlets"]]
            record["phase"] = "cutting" if target == "off" else "energizing"
            self.journal.write(self.name, record)
            for index, (outlet, sample) in enumerate(
                zip(self.entry["outlets"], samples)
            ):
                if sample["state"] != target:
                    self.interlock.begin(
                        "mains-" + target,
                        target=target,
                        index=index,
                        outlets=self.entry["outlets"],
                    )
                    # A timeout/crash leaves intent pending, including a crash before send.
                    command_id = self.adapter.switch(outlet, target)
                    protection = self.interlock.read()
                    protection["pending"]["cloud_command_id"] = command_id
                    self.interlock.journal.write(self.interlock.name, protection)
                    return
