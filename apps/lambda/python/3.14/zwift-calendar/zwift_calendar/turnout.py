"""Complete finisher counts for comparable editions of a recurring race."""

import math
from datetime import timedelta
from zoneinfo import ZoneInfo

from .api import instant
from .errors import (
    AuthenticationError,
    BudgetExceeded,
    ContractError,
    RateLimited,
    UpstreamError,
)

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
        "name": event.get("name"),
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


def lineage(row, cache, now):
    identity = row.get("parent_id")
    seen, ancestors = set(), set()
    newer = instant(row["start"])
    for _ in range(90):
        if type(identity) is not int or identity <= 0 or identity in seen:
            break
        seen.add(identity)
        event = cache.get(str(identity))
        if event is None:
            return seen, ancestors, ("event", identity)
        start = instant(event["start"])
        if start >= newer or start < now - timedelta(days=90):
            break
        ancestors.add(identity)
        newer = start
        identity = event.get("parent")
    return seen, ancestors, None


def matching_group(row, event, now):
    start = instant(event["start"])
    if not (now - timedelta(days=90) <= start <= now - timedelta(days=1)):
        return None
    if start >= instant(row["start"]) or event["type"] != row["signature"][3]:
        return None
    groups = [
        g
        for g in event["groups"]
        if g["division"] == row.get("turnout_division")
        and comparable(g["start"], row["start"])
        and instant(g["start"]) <= now - timedelta(days=1)
    ]
    return groups[0] if len(groups) == 1 else None


def family_index(cache):
    index = {}
    for identity, event in cache.items():
        if event.get("series_anchor"):
            index.setdefault(event["series_anchor"], set()).add(identity)
    return index


def evidence(row, cache, now, *, maximum=MAX_EDITIONS, index=None):
    """Use recent verified editions, including siblings of recurring templates."""
    family, ancestors, missing = lineage(row, cache, now)
    index = family_index(cache) if index is None else index
    identities = {str(identity) for identity in ancestors}
    for anchor in family:
        identities.update(index.get(anchor, set()))
    candidates = []
    for identity in identities:
        event = cache[identity]
        related = int(identity) in ancestors or (
            bool(row.get("name"))
            and event.get("name") == row["name"]
            and event.get("series_anchor") in family
        )
        if related:
            group = matching_group(row, event, now)
            if group is not None:
                candidates.append((event["start"], int(identity), group))
    editions = []
    for _, identity, group in sorted(candidates, reverse=True, key=lambda x: x[:2]):
        if "finishers" not in group:
            return editions, ("group", identity, group["id"])
        editions.append({"event_id": identity, "finishers": group["finishers"]})
        if len(editions) == maximum:
            return editions, None
    return editions, missing


def discover(state, target, events, now):
    """Enrich parent families from already fetched feed pages, without name-only joins."""
    cache = state.setdefault("turnout_events", {})
    families = []
    index = family_index(cache)
    for row in target.get("turnout", []):
        if not row.get("name"):
            continue
        family, _, _ = lineage(row, cache, now)
        anchors = {identity: identity for identity in family}
        for anchor in family:
            anchors.update(
                {int(identity): anchor for identity in index.get(anchor, set())}
            )
        families.append((row, anchors))
    for event in events:
        if event.get("sport") != "CYCLING" or event.get("eventType") not in (
            "RACE",
            "TIME_TRIAL",
        ):
            continue
        for row, anchors in families:
            if event.get("name") != row["name"] or event.get("parentId") not in anchors:
                continue
            info = metadata(event)
            parent = cache.get(str(event["parentId"]))
            if parent and instant(info["start"]) <= instant(parent["start"]):
                continue
            if matching_group(row, info, now) is None:
                continue
            identity = str(event["id"])
            info["series_anchor"] = anchors[event["parentId"]]
            previous = {g["id"]: g for g in cache.get(identity, {}).get("groups", [])}
            for group in info["groups"]:
                old = previous.get(group["id"], {})
                if (
                    old.get("division") == group["division"]
                    and old.get("start")
                    and instant(old["start"]) == instant(group["start"])
                    and "finishers" in old
                ):
                    group["finishers"] = old["finishers"]
            cache[identity] = info
            anchors[event["id"]] = info["series_anchor"]


def apply(rows, state, now):
    kept = []
    report = {
        "filtered": 0,
        "unknown": 0,
        "known": 0,
        "filtered_banded": 0,
        "filtered_unbanded": 0,
        "pending_history": 0,
        "no_parent_link": 0,
        "insufficient_history": 0,
    }
    cache = state.get("turnout_events", {})
    index = family_index(cache)
    for row in rows:
        if row.get("event_kind", "race") != "race":
            kept.append(row)
            continue
        editions, request = evidence(row, cache, now, index=index)
        average = (
            sum(e["finishers"] for e in editions) / len(editions)
            if len(editions) >= MIN_EDITIONS
            else None
        )
        reason = None
        if average is None:
            reason = (
                "pending_history"
                if request
                else "no_parent_link"
                if not row.get("parent_id")
                else "insufficient_history"
            )
        row["turnout"] = {
            "average": average,
            "editions": len(editions),
            "reason": reason,
        }
        if average is None:
            report["unknown"] += 1
            report[reason] += 1
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
    cutoff = now - timedelta(days=90)
    referenced = {str(row.get("parent_id")) for row in target.get("turnout", [])}
    referenced.update(
        str(e.get("parent")) for e in cache.values() if instant(e["start"]) >= cutoff
    )
    for identity in list(cache):
        if instant(cache[identity]["start"]) < cutoff:
            if identity in referenced:
                cache[identity] = {
                    "start": cache[identity]["start"],
                    "type": cache[identity]["type"],
                    "parent": None,
                    "groups": [],
                }
            else:
                del cache[identity]
    retries = state.setdefault("turnout_retries", {})
    rows = sorted(target.get("turnout", []), key=lambda row: (row["start"], row["id"]))
    active = {row["id"] for row in rows}
    for identity in list(retries):
        if identity not in active or retries[identity] <= now.timestamp():
            del retries[identity]
    initial = api.http.remaining
    index = family_index(cache)
    # Establish a usable average broadly before deepening already known races.
    for maximum, row in (
        (maximum, row) for maximum in (MIN_EDITIONS, MAX_EDITIONS) for row in rows
    ):
        if row["id"] in retries:
            continue
        while (
            initial - api.http.remaining < budget
            and api.http.clock() + 15 < api.http.deadline
        ):
            _, request = evidence(row, cache, now, maximum=maximum, index=index)
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
            except RateLimited, AuthenticationError:
                raise
            except BudgetExceeded:
                return
            except UpstreamError, ContractError, KeyError, TypeError, ValueError:
                retries[row["id"]] = now.timestamp() + 86400
                break
        if initial - api.http.remaining >= budget:
            break
