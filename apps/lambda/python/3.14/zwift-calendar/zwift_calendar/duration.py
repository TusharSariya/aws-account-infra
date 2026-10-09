"""Learn from anonymous finish-time histograms, never from invented lap speeds."""

import json
import math
from collections import Counter
from datetime import timedelta
from statistics import median

from .api import instant
from .errors import ContractError, UpstreamError
from .filtering import BAND, signature


def histogram(rows, subgroup):
    bins, seen = Counter(), set()
    for row in rows:
        if not isinstance(row, dict):
            raise ContractError("Invalid race result entry")
        identity = row.get("profileId")
        if (
            identity in seen
            or identity is None
            or row.get("eventSubgroupId") != subgroup
        ):
            continue
        seen.add(identity)
        if (
            row.get("qualified") is not True
            or row.get("flaggedCheating")
            or row.get("flaggedSandbagging")
            or row.get("lateJoin")
            or not isinstance(row.get("rank"), int)
            or row["rank"] <= 0
        ):
            continue
        score = (row.get("scoreHistory") or {}).get("previousScore")
        elapsed = (row.get("activityData") or {}).get("durationInMilliseconds")
        if any(
            type(x) not in (int, float) or not math.isfinite(x)
            for x in (score, elapsed)
        ):
            continue
        if not 0 <= score <= 1000 or not 0 < elapsed <= 86400000:
            continue
        bins[(score, math.ceil(elapsed / 1000))] += 1
    return [[score, seconds, count] for (score, seconds), count in sorted(bins.items())]


def learn(api, events, selected, previous, score, now, *, limit=12):
    cutoff = now - timedelta(days=90)
    cache = {
        k: v
        for k, v in previous.get("races", {}).items()
        if instant(v["start"]) >= cutoff
    }
    races = [e for e in selected if e.get("event_kind", "race") == "race"]
    wanted = {json.dumps(e["signature"]) for e in races}
    # Previously observed races become history after completion; recurring parent
    # links also supply a bounded bootstrap without scanning all riders' profiles.
    candidates = dict(previous.get("pending", {}))
    selected_ids = {e["event_id"] for e in races}
    for event in events:
        if event["id"] in selected_ids:
            candidates[str(event["id"])] = {"start": event["eventStart"]}
            if event.get("parentId"):
                candidates.setdefault(str(event["parentId"]), {"start": None})
    pending, attempted, failures = {}, 0, 0
    for identity, info in sorted(
        candidates.items(), key=lambda item: (item[1]["start"] or "", item[0])
    ):
        start = instant(info["start"]) if info["start"] else None
        if start and start < cutoff:
            continue
        if identity in cache:
            continue
        if (start and start > now - timedelta(hours=3)) or attempted >= limit:
            pending[identity] = info
            continue
        attempted += 1
        try:
            event = api.event(int(identity))
            start = instant(event["eventStart"])
            if not cutoff <= start <= now - timedelta(hours=3):
                if start > cutoff:
                    pending[identity] = {"start": start.isoformat()}
                continue
            samples = []
            for group in event["eventSubgroups"]:
                sig = signature(event, group)
                band = BAND.fullmatch(group.get("rangeAccessLabel") or "")
                if (
                    json.dumps(sig) not in wanted
                    or sig[0] is None
                    or (not sig[1] and not sig[2])
                ):
                    continue
                if group.get("rangeAccessLabel") and not band:
                    continue
                if band:
                    lower, upper = map(int, band.groups())
                    if upper < score - 50 or lower > score + 50:
                        continue
                samples.append(
                    {
                        "signature": sig,
                        "bins": histogram(api.results(group["id"]), group["id"]),
                    }
                )
            cache[identity] = {"start": start.isoformat(), "samples": samples}
        except UpstreamError, ContractError, KeyError, TypeError, ValueError:
            failures += 1
            pending[identity] = info
    return {"races": cache, "pending": pending}, {
        "history_requests": attempted,
        "history_failures": failures,
    }


def estimate(event, cache, score):
    if event["published_seconds"]:
        return {
            "seconds": math.ceil(event["published_seconds"]),
            "source": "published event duration",
            "samples": 0,
        }
    values, races = [], set()
    for identity, race in cache.get("races", {}).items():
        for sample in race["samples"]:
            if sample["signature"] != event["signature"]:
                continue
            for rider_score, seconds, count in sample["bins"]:
                if abs(rider_score - score) <= 50:
                    values.extend([seconds] * count)
                    races.add(identity)
    if len(values) >= 10 and len(races) >= 2:
        return {
            "seconds": math.ceil(median(values)),
            "source": "estimated from sampled similar-score finishers",
            "samples": len(values),
        }
    return {"seconds": 3600, "source": "estimated 60-minute placeholder", "samples": 0}
