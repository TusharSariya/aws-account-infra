"""Bounded, resumable historical sampling outside calendar publication."""

import copy
import hashlib
import json
import logging
from collections import Counter
from datetime import UTC, datetime, timedelta

from .api import Zwift, instant
from .auth import Auth
from .duration import estimate, histogram
from .errors import (
    AuthenticationError,
    BudgetExceeded,
    ContractError,
    CursorRejected,
    RateLimited,
    UpstreamError,
)
from .filtering import BAND, signature
from .storage import Busy, Parameters, Store
from .transport import Transport
from .turnout import division, populate

TARGETS = "history/targets.json"
STATE = "history/state.json"
MAX_BYTES = 5 * 1024 * 1024
MAX_PENDING = 10000
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def key(sig):
    # Feed JSON uses integers; detail JSON uses floats for the same distance.
    normalized = (
        [int(v) if isinstance(v, float) and v.is_integer() else v for v in sig]
        if isinstance(sig, list)
        else sig
    )
    return json.dumps(normalized, separators=(",", ":"))


def targets(events, selected, score, now):
    parents = {e["id"]: e.get("parentId") for e in events}
    rows = [
        e
        for e in selected
        if e.get("event_kind", "race") == "race" and not e["published_seconds"]
    ]
    counts = Counter(key(e["signature"]) for e in rows)
    return {
        "version": 1,
        "turnout": [
            {
                k: e.get(k)
                for k in (
                    "id",
                    "parent_id",
                    "start",
                    "signature",
                    "turnout_division",
                    "band",
                )
            }
            for e in selected
            if e.get("event_kind", "race") == "race"
        ],
        "updated": now.timestamp(),
        "score": score,
        "signatures": {
            key(e["signature"]): {
                "signature": e["signature"],
                "count": counts[key(e["signature"])],
                "start": min(
                    r["start"] for r in rows if r["signature"] == e["signature"]
                ),
            }
            for e in rows
        },
        "events": {
            str(e["event_id"]): {
                "start": e["start"],
                "parent": parents.get(e["event_id"]),
                "weight": counts[key(e["signature"])],
            }
            for e in rows
        },
    }


def coverage(state, target):
    signatures = target.get("signatures", {})
    covered = {
        k
        for k, row in signatures.items()
        if all(
            estimate(
                {
                    "published_seconds": 0,
                    "signature": row["signature"],
                    "turnout_division": div,
                },
                state,
                target["score"],
            )["samples"]
            for div in (
                list(
                    {
                        key(e.get("turnout_division")): e.get("turnout_division")
                        for e in target.get("turnout", [])
                        if e["signature"] == row["signature"]
                    }.values()
                )
                or [None]
            )
        )
    }
    return covered


def seed(state, target, now):
    normalized = {}
    for row in target.get("signatures", {}).values():
        identity = key(row["signature"])
        if identity in normalized:
            normalized[identity]["count"] += row["count"]
        else:
            normalized[identity] = dict(row)
    if "signatures" in target:
        target["signatures"] = normalized
    cutoff = now - timedelta(days=90)
    state.setdefault("version", 1)
    if state["version"] != 1:
        raise ContractError("Unknown backfill state version")
    state["races"] = {
        k: v for k, v in state.get("races", {}).items() if instant(v["start"]) >= cutoff
    }
    state["pending"] = {
        k: v
        for k, v in state.get("pending", {}).items()
        if not v.get("start") or instant(v["start"]) >= cutoff
    }
    scope = hashlib.sha256(
        json.dumps(
            [
                sorted(target.get("signatures", {})),
                target.get("score"),
                "canonical-complete-results-with-division-v4",
            ]
        ).encode()
    ).hexdigest()
    if state.get("scope") != scope:
        state["scope"] = scope
        # The cursor enumerates the upstream feed, independently of our targets.
        # Hourly inventory changes must not restart a multi-run scan. Newly
        # relevant events on earlier pages are revisited on the next full scan.
        # Retry metadata for the new target set; keep already learned evidence.
        for job in state["pending"].values():
            job.pop("groups", None)
            job.pop("samples", None)
    for job in state["pending"].values():
        if (
            job.get("empty_retries")
            and job.get("start")
            and instant(job["start"]) <= now - timedelta(days=1)
        ):
            job.pop("retry_after", None)
    for identity, info in target.get("events", {}).items():
        enqueue(
            state,
            identity,
            {
                "start": info["start"],
                "weight": info.get("weight", 0),
                "next_start": info["start"],
            },
        )
        if info.get("parent"):
            enqueue(
                state,
                str(info["parent"]),
                {
                    "start": None,
                    "weight": info.get("weight", 0),
                    "next_start": info["start"],
                },
            )
    return state


def enqueue(state, identity, info):
    if (
        identity in state.get("races", {})
        and state["races"][identity].get("scope") == state.get("scope")
    ) or identity in state["pending"]:
        return
    if len(state["pending"]) >= MAX_PENDING:
        state["capacity_limited"] = True
        return
    state["pending"][identity] = info


def bounded(state, target):
    """Never silently discard queued work or current-target evidence to fit."""

    def size():
        return len(json.dumps(state, separators=(",", ":")).encode())

    if size() > MAX_BYTES:
        wanted = set(target.get("signatures", {}))
        for identity, race in sorted(
            state.get("races", {}).items(), key=lambda item: item[1]["start"]
        ):
            if any(key(sample["signature"]) in wanted for sample in race["samples"]):
                continue
            del state["races"][identity]
            if size() <= MAX_BYTES:
                break
    if size() > MAX_BYTES:
        raise BudgetExceeded("Historical state capacity reached")
    return state


def admit(state, now):
    """Reserve a whole run before any upstream call, including manual invocations."""
    day, month = now.date().isoformat(), now.strftime("%Y-%m")
    slot = f"{day}:{now.hour // 3}"
    budget = state.setdefault("budget", {})
    if budget.get("month") != month:
        budget.update(month=month, monthly_runs=0)
    if budget.get("day") != day:
        budget.update(day=day, daily_runs=0)
    if (
        budget.get("slot") == slot
        or budget["daily_runs"] >= 8
        or budget["monthly_runs"] >= 248
    ):
        return False
    budget.update(
        slot=slot,
        daily_runs=budget["daily_runs"] + 1,
        monthly_runs=budget["monthly_runs"] + 1,
    )
    return True


def scan_page(api, state, target, now):
    scan = state.setdefault("scan", {"anchor": now.isoformat(), "phase": 0})
    if scan.get("complete"):
        if scan.get("completed_at", 0) > now.timestamp() - 86400:
            return False
        scan = state["scan"] = {"anchor": now.isoformat(), "phase": 0}
    if scan.get("retry_after", 0) > now.timestamp():
        return False
    anchor = instant(scan["anchor"])
    days = (7, 30, 90)[scan["phase"]]
    since = anchor - timedelta(days=days)
    try:
        rows, cursor = api.history_page(since, scan.get("cursor"))
    except CursorRejected:
        scan.pop("cursor", None)
        scan["seen_cursors"] = []
        scan["retry_after"] = now.timestamp() + 86400
        scan["resets"] = scan.get("resets", 0) + 1
        return False
    # Event-parent timestamps are not a pagination stopping boundary.
    for event in rows:
        if not since <= instant(event["eventStart"]) <= now - timedelta(hours=3):
            continue
        if event.get("sport") != "CYCLING" or event.get("eventType") not in (
            "RACE",
            "TIME_TRIAL",
        ):
            continue
        if any(
            key(signature(event, g)) in target["signatures"]
            for g in event.get("eventSubgroups", [])
        ):
            enqueue(state, str(event["id"]), {"start": event["eventStart"]})
    seen = scan.setdefault("seen_cursors", [])
    if cursor and cursor in seen:
        raise ContractError("Repeated historical cursor")
    if cursor:
        if len(seen) >= 10000:
            raise ContractError("Historical pagination limit reached")
        seen.append(cursor)
        scan["cursor"] = cursor
    else:
        scan.pop("cursor", None)
        scan["seen_cursors"] = []
        scan["phase"] += 1
        if scan["phase"] == 3:
            scan.update(complete=True, completed_at=now.timestamp())
    return True


def sample_event(api, state, identity, target, now):
    job = state["pending"][identity]
    if "groups" not in job:
        event = api.event(int(identity))
        start = instant(event["eventStart"])
        job["start"] = start.isoformat()
        if start < now - timedelta(days=90):
            del state["pending"][identity]
            return
        if start > now - timedelta(hours=3):
            job["retry_after"] = (start + timedelta(hours=3)).timestamp()
            return
        parent = event.get("parentId")
        # Only follow parents backward in time; visited IDs also prevent cycles.
        if type(parent) is int and parent > 0 and parent != int(identity):
            enqueue(
                state,
                str(parent),
                {
                    "start": None,
                    "weight": job.get("weight", 0),
                    "next_start": job.get("next_start"),
                },
            )
        job["groups"] = []
        for group in event.get("eventSubgroups", []):
            sig = signature(event, group)
            wanted_divisions = [
                e.get("turnout_division")
                for e in target.get("turnout", [])
                if e["signature"] == sig
            ]
            if wanted_divisions and division(group) not in wanted_divisions:
                continue
            label = group.get("rangeAccessLabel")
            band = BAND.fullmatch(label or "")
            if (
                key(sig) not in target["signatures"]
                or sig[0] is None
                or not (sig[1] or sig[2])
            ):
                continue
            if label and not band:
                continue
            if band:
                low, high = map(int, band.groups())
                if high < target["score"] - 50 or low > target["score"] + 50:
                    continue
            job["groups"].append(
                {"id": group["id"], "signature": sig, "division": division(group)}
            )
        job["samples"] = []
    if job["groups"]:
        group = job["groups"][0]
        bins = histogram(api.results(group["id"]), group["id"])
        if (
            not bins
            and job.get("empty_retries", 0) < 1
            and instant(job["start"]) > now - timedelta(days=1)
        ):
            job.update(empty_retries=1, retry_after=now.timestamp() + 86400)
            return
        job["samples"].append(
            {
                "signature": group["signature"],
                "subgroup_id": group["id"],
                "bins": bins,
                "division": group.get("division"),
            }
        )
        job["groups"].pop(0)
        job.pop("empty_retries", None)
    if not job["groups"]:
        state.setdefault("races", {})[identity] = {
            "start": job["start"],
            "samples": job["samples"],
            "scope": state.get("scope"),
        }
        del state["pending"][identity]


def run_batch(api, state, target, now, checkpoint):
    """One transaction per unit; interrupted units are safe to replay."""
    covered = coverage(state, target)
    wanted = {k: v for k, v in target.get("signatures", {}).items() if k not in covered}
    work = target | {"signatures": wanted}
    requests_at_save = api.http.remaining
    saves = 0
    discovery = 0
    while api.http.remaining > 0 and api.http.clock() + 15 < api.http.deadline:
        if not wanted:
            break
        due = [
            k
            for k, v in state["pending"].items()
            if v.get("retry_after", 0) <= now.timestamp()
            and (not v.get("start") or instant(v["start"]) <= now - timedelta(hours=3))
        ]
        # Bootstrap recurring history first, but discovery cannot be starved.
        discover = not due or (discovery < 40 and (120 - api.http.remaining) % 3 == 0)
        before = copy.deepcopy(state)
        try:
            if discover:
                remaining = api.http.remaining
                progressed = scan_page(api, state, work, now)
                discovery += max(1, remaining - api.http.remaining)
                if not progressed:
                    discovery = 40
                    if not due:
                        break
                    continue
            elif due:

                def priority(identity, wanted=wanted):
                    job = state["pending"][identity]
                    groups = job.get("groups", [])
                    rank = max(
                        (
                            wanted.get(key(g["signature"]), {}).get("count", 0)
                            for g in groups
                        ),
                        default=0,
                    )
                    return (
                        -max(rank, job.get("weight", 0)),
                        job.get("next_start") or job.get("start") or "",
                        identity,
                    )

                identity = min(due, key=priority)
                sample_event(api, state, identity, work, now)
            else:
                break
            bounded(state, target)
            state["successful_units"] = state.get("successful_units", 0) + 1
        except RateLimited as exc:
            state.clear()
            state.update(before)
            state["retry_after"] = now.timestamp() + exc.seconds
            break
        except BudgetExceeded:
            state.clear()
            state.update(before)
            state["capacity_limited"] = (
                len(json.dumps(before).encode()) > MAX_BYTES * 0.9
            )
            break
        except AuthenticationError:
            raise
        except UpstreamError, ContractError, KeyError, TypeError, ValueError:
            state.clear()
            state.update(before)
            state["failures"] = state.get("failures", 0) + 1
            if not discover and due:
                job = state["pending"][identity]
                job["retry_after"] = now.timestamp() + 86400
            else:
                break
        if requests_at_save - api.http.remaining >= 30 and saves < 3:
            checkpoint(state)
            saves += 1
            requests_at_save = api.http.remaining
        covered = coverage(state, target)
        wanted = {k: v for k, v in target["signatures"].items() if k not in covered}
        work = target | {"signatures": wanted}
    return state


def status(state, target):
    covered = coverage(state, target) if target.get("signatures") else set()
    return {
        "version": 1,
        "covered_signatures": len(covered),
        "target_signatures": len(target.get("signatures", {})),
        "placeholder_events": sum(
            r["count"]
            for k, r in target.get("signatures", {}).items()
            if k not in covered
        ),
        "races": len(state.get("races", {})),
        "pending": len(state.get("pending", {})),
        "samples": sum(
            sum(b[2] for b in s["bins"])
            for r in state.get("races", {}).values()
            for s in r["samples"]
        ),
        "budget": state.get("budget", {}),
        "last_success": state.get("last_success"),
        "retry_after": state.get("retry_after"),
        "capacity_limited": state.get("capacity_limited", False),
        "scan": {
            k: v
            for k, v in state.get("scan", {}).items()
            if k not in ("cursor", "seen_cursors")
        },
    }


def refresh_history(store, parameters, http, now):
    try:
        store.claim()
    except Busy:
        return {"status": "busy"}
    try:
        state, etag = store.read(STATE)
        target, _ = store.read(TARGETS)
        if not state:
            legacy, _ = store.read("private.json")
            state = copy.deepcopy(legacy.get("history", {})) | {"version": 1}
        seed(state, target, now)

        def save(value):
            nonlocal etag
            etag = store.private_write(STATE, bounded(value, target), etag)

        if not target or now.timestamp() - target.get("updated", 0) > 86400:
            return {"status": "no_targets"}
        if state.get("retry_after", 0) > now.timestamp():
            return {"status": "deferred", **status(state, target)}
        if not admit(state, now):
            return {"status": "budget_limited", **status(state, target)}
        save(state)
        if target.get("turnout") or len(coverage(state, target)) < len(
            target["signatures"]
        ):
            before = state.get("successful_units", 0)
            try:
                token = Auth(http, parameters, store).access()
                api = Zwift(http, token)
                populate(api, state, target, now)
                run_batch(api, state, target, now, save)
            except RateLimited as exc:
                state["retry_after"] = now.timestamp() + exc.seconds
            if state.get("successful_units", 0) > before:
                state["last_success"] = now.timestamp()
        else:
            state["last_success"] = now.timestamp()
        state["requests"] = 120 - http.remaining
        save(state)
        return {"status": "ok", **status(state, target), "requests": state["requests"]}
    finally:
        store.release()


def handler(event, context):
    try:
        from .bootstrap import refresh as bootstrap

        worker = bootstrap if event.get("mode") == "bootstrap" else refresh_history
        extra = {"run_id": event.get("run_id")} if worker is bootstrap else {}
        result = worker(
            Store(),
            Parameters(),
            Transport(budget=120, seconds=150, interval=0.5, defer_rate_limits=True),
            datetime.now(UTC),
            **extra,
        )
        log.info("Zwift history: %s", json.dumps(result))
        return result
    except Exception:  # noqa: BLE001 - redact SDK and upstream payloads
        raise RuntimeError(
            "Zwift historical backfill failed; previous calendar retained"
        ) from None
