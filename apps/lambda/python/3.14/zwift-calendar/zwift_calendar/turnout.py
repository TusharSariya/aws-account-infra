"""Complete finisher counts for comparable editions of a recurring race."""

import math
from datetime import timedelta
from zoneinfo import ZoneInfo

from .api import instant
from .errors import BudgetExceeded, ContractError, RateLimited, UpstreamError

ZONE = ZoneInfo("America/St_Johns")
MIN_EDITIONS = 2
MAX_EDITIONS = 6
MIN_FINISHERS = 10


def division(group):
    band = group.get("rangeAccessLabel")
    if band:
        return ["score", band.replace("–", "-").replace(" ", "")]
    pace = [group.get(k) for k in ("fromPaceValue", "toPaceValue")]
    if any(
        v is not None and (type(v) not in (int, float) or not math.isfinite(v))
        for v in pace
    ):
        raise ContractError("Invalid historical pace range")
    return ["legacy", group.get("label"), *pace]


def metadata(event):
    return {
        "parent": event.get("parentId"),
        "start": event["eventStart"],
        "type": event["eventType"],
        "groups": [
            {"id": g["id"], "division": division(g), "start": g["eventSubgroupStart"]}
            for g in event["eventSubgroups"]
        ],
    }


def comparable(start, upcoming):
    a, b = instant(start).astimezone(ZONE), instant(upcoming).astimezone(ZONE)
    return (a.weekday(), a.hour, a.minute) == (b.weekday(), b.hour, b.minute)


def evidence(row, cache, now):
    """Return known editions and the next missing piece of their parent chain."""
    identity = row.get("parent_id")
    seen, editions = set(), []
    newer = instant(row["start"])
    for _ in range(90):
        if type(identity) is not int or identity <= 0 or identity in seen:
            break
        seen.add(identity)
        event = cache.get(str(identity))
        if event is None:
            return editions, ("event", identity)
        start = instant(event["start"])
        if start >= newer or start < now - timedelta(days=90):
            break
        newer = start
        if start <= now - timedelta(days=1) and event["type"] == row["signature"][3]:
            groups = [
                g
                for g in event["groups"]
                if g["division"] == row.get("turnout_division")
                and comparable(g["start"], row["start"])
            ]
            # Ambiguous historical divisions are unknown, never combined.
            if len(groups) == 1:
                group = groups[0]
                if "finishers" not in group:
                    return editions, ("group", identity, group["id"])
                editions.append({"event_id": identity, "finishers": group["finishers"]})
                if len(editions) == MAX_EDITIONS:
                    break
        identity = event.get("parent")
    return editions, None


def apply(rows, state, now):
    kept = []
    report = {
        "filtered": 0,
        "unknown": 0,
        "known": 0,
        "filtered_banded": 0,
        "filtered_unbanded": 0,
    }
    cache = state.get("turnout_events", {})
    for row in rows:
        if row.get("event_kind", "race") != "race":
            kept.append(row)
            continue
        editions, _ = evidence(row, cache, now)
        average = (
            sum(e["finishers"] for e in editions) / len(editions)
            if len(editions) >= MIN_EDITIONS
            else None
        )
        row["turnout"] = {"average": average, "editions": len(editions)}
        if average is None:
            report["unknown"] += 1
        else:
            report["known"] += 1
            if average < MIN_FINISHERS:
                report["filtered"] += 1
                report[
                    "filtered_banded"
                    if row["band"] is not None
                    else "filtered_unbanded"
                ] += 1
                continue
        kept.append(row)
    return kept, report


def populate(api, state, target, now, *, budget=40):
    """Share the worker's existing request budget; store aggregates only."""
    cache = state.setdefault("turnout_events", {})
    for identity in list(cache):
        if instant(cache[identity]["start"]) < now - timedelta(days=90):
            del cache[identity]
    retries = state.setdefault("turnout_retries", {})
    rows = sorted(target.get("turnout", []), key=lambda row: (row["start"], row["id"]))
    active = {row["id"] for row in rows}
    for identity in list(retries):
        if identity not in active or retries[identity] <= now.timestamp():
            del retries[identity]
    initial = api.http.remaining
    for row in rows:
        if row["id"] in retries:
            continue
        while (
            initial - api.http.remaining < budget
            and api.http.clock() + 15 < api.http.deadline
        ):
            _, request = evidence(row, cache, now)
            if request is None:
                break
            try:
                if request[0] == "event":
                    cache[str(request[1])] = metadata(api.event(request[1]))
                else:
                    count = api.finisher_count(request[2])
                    for group in cache[str(request[1])]["groups"]:
                        if group["id"] == request[2]:
                            group["finishers"] = count
                state["successful_units"] = state.get("successful_units", 0) + 1
            except RateLimited:
                raise
            except BudgetExceeded:
                return
            except UpstreamError, ContractError, KeyError, TypeError, ValueError:
                retries[row["id"]] = now.timestamp() + 86400
                break
        if initial - api.http.remaining >= budget:
            break
