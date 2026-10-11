"""Hourly extraction and read-only feed endpoints."""

import json
import logging
import os
from datetime import UTC, datetime, timedelta

from .api import Zwift, instant
from .auth import Auth
from .backfill import STATE, TARGETS, targets
from .backfill import status as history_status
from .calendar import CALENDAR_NAMES, split_calendars
from .duration import estimate
from .errors import ContractError, UpstreamError
from .filtering import select
from .storage import Busy, Parameters, Store
from .transport import Transport
from .turnout import apply as apply_turnout

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def weekly_counts(selected, now):
    """Count event slots, not all category pens or distinct campaign stages."""
    weeks = []
    for index in range(2):
        start, end = (
            now + timedelta(days=index * 7),
            now + timedelta(days=(index + 1) * 7),
        )
        rows = [e for e in selected if start <= instant(e["start"]) < end]
        weeks.append(
            {
                "from": start.isoformat(),
                "until": end.isoformat(),
                "total": len(rows),
                "score_banded_races": sum(
                    e.get("event_kind", "race") == "race" and e["band"] is not None
                    for e in rows
                ),
                "unbanded_races": sum(
                    e.get("event_kind", "race") == "race" and e["band"] is None
                    for e in rows
                ),
                "special_event_rides": sum(
                    e.get("event_kind") == "special_ride" for e in rows
                ),
            }
        )
    return weeks


def collect(api, state, now):
    degraded = False
    try:
        profile = api.profile(now)
    except UpstreamError, ContractError:
        profile = state.get("profile")
        if not profile or not 0 <= now.timestamp() - profile["retrieved_at"] <= 86400:
            raise
        degraded = True
    events = api.upcoming(now + timedelta(days=14))
    selected, exclusions = select(events, profile, now)
    candidates = list(selected)
    score = next(
        (profile[key] for key in ("current", "max30") if profile[key] is not None), 100
    )
    history = state.get("history", {})
    history = history | {
        "races": {
            k: v
            for k, v in history.get("races", {}).items()
            if instant(v["start"]) >= now - timedelta(days=90)
        }
    }
    for event in selected:
        event["duration"] = estimate(event, history, score)
    selected, turnout_report = apply_turnout(selected, history, now)
    snapshot, revisions = split_calendars(selected, state.get("revisions", {}), now)
    report = {
        "matched": len(selected),
        "before_turnout_filter": len(candidates),
        "turnout": turnout_report,
        "weekly_counts": weekly_counts(selected, now),
        "excluded": exclusions,
        "discovered": len(events),
        "score_age_seconds": int(now.timestamp() - profile["retrieved_at"]),
        "score_degraded": degraded,
        "provisional": profile["current"] is None and profile["max30"] is None,
        "window_start": now.isoformat(),
        "window_end": (now + timedelta(days=14)).isoformat(),
        "latest_matching_start": max((e["start"] for e in selected), default=None),
        "latest_published_start": max((e["eventStart"] for e in events), default=None),
        "estimated_from_history": sum(e["duration"]["samples"] > 0 for e in selected),
        "history_requests": 0,
        "history_failures": 0,
    }
    return (
        snapshot,
        {
            "profile": profile,
            "history": history,
            "revisions": revisions,
            "_targets": targets(events, candidates, score, now),
        },
        report,
    )


def refresh(store, parameters, http, now, *, preview=False):
    try:
        previous = store.claim()
    except Busy:
        return {"status": "busy"}
    try:
        state, etag = store.read("private.json")
        learned, _ = store.read(STATE)
        if learned:
            if learned.get("version") != 1:
                raise ContractError("Unknown historical state version")
            state["history"] = learned
        published_revisions = state.get("revisions", {})
        token = Auth(http, parameters, store).access()
        snapshot, state, report = collect(Zwift(http, token), state, now)
        next_targets = state.pop("_targets", None)
        if learned:
            state.pop("history", None)
        if preview:
            state["revisions"] = published_revisions
        store.private_write("private.json", state, etag)
        if not preview:
            if next_targets is not None:
                _, target_etag = store.read(TARGETS)
                store.private_write(TARGETS, next_targets, target_etag)
            store.publish(snapshot)
        return {
            "status": "degraded" if report["score_degraded"] else "ok",
            "report": report,
            "changed": any(
                feed["etag"] != previous.get("calendars", {}).get(key, {}).get("etag")
                for key, feed in snapshot["calendars"].items()
            ),
            **({"calendars": snapshot["calendars"]} if preview else {}),
        }
    finally:
        store.release()


def sync_handler(event, context):
    try:
        result = refresh(Store(), Parameters(), Transport(), datetime.now(UTC))
        log.info("Zwift sync: %s", json.dumps(result))
        if result["status"] == "degraded":
            raise UpstreamError(
                "Calendar updated using cached score; score refresh failed"
            )
        return result
    except Exception:  # noqa: BLE001 - sanitize upstream/SDK data at the Lambda boundary
        raise RuntimeError(
            "Zwift calendar sync failed; inspect freshness and authentication status"
        ) from None


def serve(event, store, now):
    data, _ = store.read()
    if event.get("health") is True:
        if (
            now.timestamp() - data.get("last_success", 0) > 10800
            or set(data.get("calendars", {})) != set(CALENDAR_NAMES)
            or any(
                not feed.get("ics") or not feed.get("etag")
                for feed in data.get("calendars", {}).values()
            )
        ):
            raise RuntimeError("Zwift calendars are missing or older than three hours")
        if os.environ.get("HISTORY_ENABLED") == "true":
            historical, _ = store.read(STATE)
            target, _ = store.read(TARGETS)
            report = history_status(historical, target)
            if (
                report["placeholder_events"]
                and now.timestamp() - (historical.get("last_success") or 0) > 86400
            ):
                raise RuntimeError("Historical backfill has not succeeded for 24 hours")
        return {"status": "ok"}
    routes = {f"GET /calendars/zwift-{key}.ics": key for key in CALENDAR_NAMES}
    key = routes.get(event.get("routeKey"))
    if key is None:
        return {"statusCode": 404, "body": "Not found"}
    feed = data.get("calendars", {}).get(key)
    if not feed:
        return {
            "statusCode": 503,
            "headers": {"Retry-After": "300"},
            "body": "Calendar is initializing",
        }
    headers = {
        "Content-Type": "text/calendar; charset=utf-8",
        "ETag": feed["etag"],
        "Cache-Control": "public, max-age=300",
        "Content-Disposition": f'inline; filename="zwift-{key}.ics"',
    }
    request = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    tags = [
        s.strip().removeprefix("W/")
        for s in request.get("if-none-match", "").split(",")
    ]
    if "*" in tags or feed["etag"] in tags:
        return {"statusCode": 304, "headers": headers, "body": ""}
    return {"statusCode": 200, "headers": headers, "body": feed["ics"]}


def feed_handler(event, context):
    return serve(event, Store(), datetime.now(UTC))
