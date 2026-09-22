"""Pure retained-host lifecycle. Effects require a durable journal before execution.

No wall-clock idle accounting: the caller supplies a monotonic clock and resets
observations on process restart. Failed/uncertain effects require operator recovery.
"""

from dataclasses import asdict, dataclass, field

HOSTS = frozenset({"primary", "secondary"})
MODES = frozenset({"observe", "wake", "automatic"})


@dataclass
class Observation:
    power: str = "unknown"
    identity_ok: bool = False
    ready: bool = False
    restore_ready: bool = True
    demand: bool = False
    blockers: list[str] = field(default_factory=list)
    complete: bool = False
    retirement_ready: bool = True
    quiesced: bool = False
    vm_stopped: bool = False
    host_empty: bool = False


@dataclass
class State:
    phase: str = "unknown"
    paused: bool = False
    idle_since: float | None = None
    last_sample: float | None = None
    deadline: float | None = None
    pending: str | None = None
    reason: str = ""
    operation: int = 0
    shutdown_requested: bool = False
    wake_requested: bool = False

    def restart(self):
        self.idle_since = self.last_sample = self.deadline = None
        if self.pending or self.phase in {
            "waking",
            "restoring",
            "draining",
            "stopping",
        }:
            self.phase = "blocked"
            self.reason = "Interrupted transition; inspect observed state before resume"
        self.pending = None

    def to_dict(self):
        return asdict(self)


def decide(
    state: State,
    obs: Observation,
    now: float,
    *,
    mode="observe",
    idle_seconds=1800,
    recovery_seconds=1200,
    sample_gap=60,
):
    """Return at most one effect. Persist changed state before issuing it.

    Commands: wake (IMM), restore (VM/readiness), quiesce, cancel,
    stop-worker (Talos), stop-host (orderly PVE). Never forced power-off.
    """
    if mode not in MODES:
        raise ValueError("Unknown rollout mode")
    if (
        state.last_sample is None
        or now - state.last_sample > sample_gap
        or now < state.last_sample
    ):
        state.idle_since = None
    state.last_sample = now
    if state.phase == "blocked":
        return None
    if obs.power not in {"on", "off"} or not obs.identity_ok:
        state.idle_since = None
        state.reason = "Power or registered identity is unknown"
        return None
    if state.deadline is not None and now >= state.deadline:
        state.phase = "blocked"
        state.reason = "Recovery deadline exceeded; inspect before resume"
        return None
    if state.pending:
        return None
    demand = obs.demand or state.wake_requested

    def effect(action, phase):
        if mode == "observe" or (
            mode == "wake" and action not in {"wake", "restore", "cancel"}
        ):
            state.reason = "Rollout mode suppresses " + action
            return None
        state.phase, state.pending = phase, action
        state.operation += 1
        state.idle_since = None
        state.reason = action
        if state.deadline is None:
            state.deadline = now + recovery_seconds
        return action

    if obs.power == "off":
        state.phase = "off"
        state.shutdown_requested = False
        state.deadline = None
        state.idle_since = None
        if demand and not state.paused:
            return effect("wake", "waking")
        state.reason = "Maintenance pause" if state.paused else "No demand"
        return None
    # A committed shutdown finishes even if demand arrives. The following off
    # observation starts wake. This avoids conflicting ACPI and power-on requests.
    if state.phase == "stopping":
        if obs.vm_stopped and obs.host_empty:
            return effect("stop-host", "stopping")
        state.reason = "Waiting for worker shutdown and empty host"
        return None
    if state.phase == "draining":
        if (
            demand
            or (state.paused and not state.shutdown_requested)
            or not obs.complete
            or obs.blockers
        ):
            return effect("cancel", "restoring")
        if obs.quiesced and obs.retirement_ready:
            return effect("stop-worker", "stopping")
        return effect("quiesce", "draining")
    if state.paused and not state.shutdown_requested:
        state.idle_since = None
        state.reason = "Maintenance pause"
        return None
    if not obs.ready:
        state.idle_since = None
        if demand or state.phase in {"waking", "restoring"}:
            if not obs.restore_ready:
                state.phase = "waking"
                if state.deadline is None:
                    state.deadline = now + recovery_seconds
                state.reason = "Waiting for Proxmox bootstrap"
                return None
            return effect("restore", "restoring")
        state.reason = "Worker not ready; automatic shutdown prohibited"
        return None
    state.phase, state.deadline = "ready", None
    state.wake_requested = False
    if demand or not obs.complete or obs.blockers:
        state.idle_since = None
        state.reason = "Demand or activity: " + ", ".join(obs.blockers)
        return None
    state.phase = "idle"
    if state.idle_since is None:
        state.idle_since = now
    if obs.retirement_ready and (
        state.shutdown_requested or now - state.idle_since >= idle_seconds
    ):
        return effect("quiesce", "draining")
    state.reason = "Verified idle"
    return None


def complete(state: State, action: str, *, error: str | None = None):
    if state.pending != action:
        raise ValueError("Effect does not match journal")
    state.pending = None
    if error:
        state.phase, state.reason = "blocked", error
        state.idle_since = None
    elif action == "cancel":
        state.phase = "restoring"
        state.shutdown_requested = False
    elif action == "wake":
        state.pending = "await-on"
    elif action == "stop-host":
        # Do not retry an acknowledged shutdown. Wait for observed IMM off.
        state.pending = "await-off"


def observe_off(state: State, obs: Observation):
    if state.pending == "await-on" and obs.power == "on" and obs.identity_ok:
        state.pending = None
    if state.pending == "await-off" and obs.power == "off" and obs.identity_ok:
        state.pending = None
        state.phase = "off"
