"""Private, recency-weighted sustained power. No FTP or score inputs."""

import math
from bisect import bisect_left
from datetime import UTC
from io import BytesIO
from itertools import accumulate, pairwise

import fitdecode

from .api import instant
from .errors import ContractError

DEFAULT_POINTS = [(300, 120), (1200, 105), (3600, 100), (7200, 90), (14400, 80)]


def weight(completed, now):
    age = (now - instant(completed)).total_seconds() / 86400
    return (1 - int(age // 7) * 0.25) if 0 <= age < 28 else 0


def recording_curve(messages, check_budget=lambda: None):
    """One-second samples only. Missing seconds, invalid power and timer stops split efforts.

    A record supplies the power for the preceding second. No interpolation over
    gaps, and genuine zero watts remain in every sustained average.
    """
    blocks, block, previous, running = [], [], None, True
    for message in messages:
        check_budget()
        kind = message.get("kind", "record")
        if kind == "event" and message.get("event") == "timer":
            if block:
                blocks.append(block)
            block, previous = [], None
            running = message.get("event_type") == "start"
            continue
        if kind != "record":
            continue
        stamp, watts = message.get("timestamp"), message.get("power")
        valid = (
            running
            and stamp is not None
            and type(watts) in (int, float)
            and math.isfinite(watts)
            and 0 <= watts <= 3000
        )
        contiguous = (
            previous is not None
            and stamp is not None
            and (stamp - previous).total_seconds() == 1
        )
        if not valid or not contiguous:
            if block:
                blocks.append(block)
            block = []
        if valid:
            block.append(watts)
        previous = stamp if valid else None
    if block:
        blocks.append(block)
    result = {}
    for block in blocks:
        prefix = list(accumulate(block, initial=0))
        for seconds in range(60, len(block) + 1, 60):
            check_budget()
            best = (
                max(
                    prefix[i] - prefix[i - seconds] for i in range(seconds, len(prefix))
                )
                / seconds
            )
            result[str(seconds)] = max(result.get(str(seconds), 0), round(best, 4))
    return result


def fit_curve(data, check_budget=lambda: None):
    try:
        with fitdecode.FitReader(
            BytesIO(data), check_crc=fitdecode.CrcCheck.RAISE
        ) as reader:

            def messages():
                for frame in reader:
                    check_budget()
                    if isinstance(frame, fitdecode.FitDataMessage) and frame.name in (
                        "record",
                        "event",
                    ):
                        row = {field.name: field.value for field in frame.fields}
                        if row.get("timestamp"):
                            row["timestamp"] = row["timestamp"].replace(tzinfo=UTC)
                        yield row | {"kind": frame.name}

            return recording_curve(messages(), check_budget)
    except (fitdecode.FitError, ValueError, TypeError) as exc:
        raise ContractError("Invalid FIT recording") from exc


class PowerCurve:
    def __init__(self, activities, now, default_points=None):
        if default_points is not None and (
            len(default_points) < 2
            or any(
                len(point) != 2
                or any(
                    type(v) not in (int, float) or not math.isfinite(v) or v <= 0
                    for v in point
                )
                for point in default_points
            )
            or any(b[0] <= a[0] or b[1] > a[1] for a, b in pairwise(default_points))
        ):
            raise ValueError(
                "Default power curve must have increasing durations and non-increasing positive power"
            )
        self.activities = [
            a for a in activities if weight(a["completed"], now) and a.get("curve")
        ]
        totals, weights, counts, contributors = {}, {}, {}, {}
        for index, activity in enumerate(self.activities):
            w = weight(activity["completed"], now)
            for duration, watts in activity["curve"].items():
                seconds = int(duration)
                totals[seconds] = totals.get(seconds, 0) + watts * w
                weights[seconds] = weights.get(seconds, 0) + w
                counts[seconds] = counts.get(seconds, 0) + 1
                contributors.setdefault(seconds, set()).add(index)
        self.default = not totals
        self.counts = counts
        points = (
            sorted((s, totals[s] / weights[s]) for s in totals)
            if totals
            else (default_points or DEFAULT_POINTS)
        )
        self.points, floor = [], math.inf
        self.dependencies, dependencies = {}, set()
        for seconds, watts in points:
            if seconds <= 0 or not math.isfinite(watts) or watts <= 0:
                # An all-zero activity is evidence of no supported positive effort.
                continue
            if watts <= floor:
                dependencies = contributors.get(seconds, set())
            floor = min(floor, watts)
            self.dependencies[seconds] = dependencies
            self.points.append((seconds, floor))
        if not self.points:
            self.default, self.activities = True, []
            self.counts = {}
            self.points = list(default_points or DEFAULT_POINTS)
        self.assumed_exponent = False
        if self.default:
            (a, p), (b, q) = self.points[-2:]
            self.exponent = -math.log(q / p) / math.log(b / a)
        else:
            supported = [(math.log(s), math.log(p)) for s, p in self.points if s >= 600]
            if len(supported) < 2:
                self.exponent, self.assumed_exponent = 0.1, True
            else:
                mx = sum(x for x, _ in supported) / len(supported)
                my = sum(y for _, y in supported) / len(supported)
                slope = sum((x - mx) * (y - my) for x, y in supported) / sum(
                    (x - mx) ** 2 for x, _ in supported
                )
                self.exponent = min(0.5, max(0, -slope))

    def watts(self, seconds):
        if seconds <= self.points[0][0]:
            return self.points[0][1]
        if seconds > self.points[-1][0]:
            duration, watts = self.points[-1]
            return watts * (seconds / duration) ** -self.exponent
        i = bisect_left([s for s, _ in self.points], seconds)
        a, p = self.points[i - 1]
        b, q = self.points[i]
        fraction = math.log(seconds / a) / math.log(b / a)
        return math.exp(math.log(p) + fraction * math.log(q / p))

    def evidence(self, seconds):
        durations = [s for s, _ in self.points]
        extrapolated = seconds > durations[-1] or seconds < durations[0]
        if seconds > durations[-1]:
            used = (
                [durations[-1]]
                if self.assumed_exponent
                else [s for s in durations if s >= 600] + [durations[-1]]
            )
        elif seconds <= durations[0]:
            used = [durations[0]]
        else:
            i = bisect_left(durations, seconds)
            used = (
                [durations[i]] if seconds == durations[i] else durations[i - 1 : i + 1]
            )
        indices = set().union(*(self.dependencies.get(s, set()) for s in used))
        dates = sorted(self.activities[i]["completed"][:10] for i in indices)
        counts = [self.counts.get(s, 0) for s in used]
        return {
            "power_source": "default"
            if self.default
            else "extrapolated"
            if extrapolated
            else "measured",
            "activities": len(indices),
            "duration_support_min": min(counts),
            "duration_support_max": max(counts),
            "evidence_dates": [dates[0], dates[-1]] if dates else [],
            "sparse": not self.default and min(counts) < 3,
            "assumed_endurance_exponent": self.assumed_exponent
            if extrapolated
            else False,
        }
