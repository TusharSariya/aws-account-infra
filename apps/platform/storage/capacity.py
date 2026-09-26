"""Fail-closed capacity policy. No I/O, admission side effects or deletion paths."""
from dataclasses import dataclass
import math

SAMPLE_SECONDS = 30
MAX_AGE_SECONDS = 90
RECOVERY_SECONDS = 300
# A missing or stale sample closes admission at once but only drains running work
# once it has persisted this long: one sampler gap is not storage pressure.
UNPROVEN_DRAIN_SECONDS = 180
WARN_PERCENT = 80
STOP_PERCENT = 90


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


@dataclass(frozen=True)
class Decision:
    admission: bool
    drain: bool
    warning: bool
    reasons: tuple[str, ...]


class CapacityGate:
    """Use monotonic time for intervals and wall time only to validate samples.

    Reconstruct after controller recovery to discard unproven continuity. Persist
    the returned drain request as desired=off; clearing a gate is never Start.
    """

    def __init__(self, expected):
        if not expected or any(not isinstance(v, str) or not v for v in expected.values()):
            raise ValueError('Explicit identities required for all measurements')
        self.expected = dict(expected)
        self.latched = True
        self.healthy_since = None
        self.last_tick = None
        self.unproven_since = None

    def evaluate(self, samples, *, wall_time, monotonic_time):
        reasons, percents = [], []
        if not finite_number(wall_time) or not finite_number(monotonic_time):
            raise ValueError('Finite clocks required')
        gap = self.last_tick is not None and not (0 <= monotonic_time - self.last_tick <= MAX_AGE_SECONDS)
        self.last_tick = monotonic_time
        if gap:
            self.healthy_since = None
        if not isinstance(samples, dict):
            samples = {}
        unproven = []
        for name, identity in self.expected.items():
            sample = samples.get(name)
            if not isinstance(sample, dict):
                unproven.append(name + ': missing measurement')
                continue
            measured = sample.get('measured_at')
            percent = sample.get('used_percent')
            if sample.get('identity') != identity:
                reasons.append(name + ': identity mismatch')
            elif sample.get('healthy') is not True:
                reasons.append(name + ': unhealthy')
            elif not finite_number(measured) or not 0 <= wall_time - measured <= MAX_AGE_SECONDS:
                unproven.append(name + ': stale or invalid timestamp')
            elif not finite_number(percent) or not 0 <= percent <= 100:
                reasons.append(name + ': invalid usage')
            else:
                percents.append(percent)
                if percent >= STOP_PERCENT:
                    reasons.append(name + ': critical capacity')
        # Absent evidence is fail-closed for admission immediately, and becomes a
        # drain only after UNPROVEN_DRAIN_SECONDS of continuous absence.
        if unproven:
            if self.unproven_since is None or gap:
                self.unproven_since = monotonic_time
            if monotonic_time - self.unproven_since >= UNPROVEN_DRAIN_SECONDS:
                reasons.extend(unproven)
        else:
            self.unproven_since = None
        critical = bool(reasons)
        if unproven and not critical:
            # Continuity is unproven: close admission and require a fresh healthy interval.
            self.latched = True
            self.healthy_since = None
            return Decision(False, False, True, tuple(unproven))
        warning = any(percent >= WARN_PERCENT for percent in percents)
        if critical:
            self.latched = True
            self.healthy_since = None
        elif warning:
            self.healthy_since = None
        elif self.latched:
            if self.healthy_since is None:
                self.healthy_since = monotonic_time
            if monotonic_time - self.healthy_since >= RECOVERY_SECONDS:
                self.latched = False
        if self.latched and not reasons:
            reasons.append('awaiting five continuous healthy minutes below 80 percent')
        return Decision(not self.latched, critical, warning or critical, tuple(reasons))
