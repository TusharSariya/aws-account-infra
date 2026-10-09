"""Hourly extraction and read-only feed endpoints."""

import json
import logging
from datetime import UTC, datetime, timedelta

from .api import Zwift
from .auth import Auth
from .calendar import reconcile
from .duration import estimate, learn
from .errors import ContractError, UpstreamError
from .filtering import select
from .storage import Busy, Parameters, Store
from .transport import Transport

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


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
    score = next(
        (profile[key] for key in ("current", "max30") if profile[key] is not None), 100
    )
    history, history_report = learn(
        api, events, selected, state.get("history", {}), score, now
    )
    for event in selected:
        event["duration"] = estimate(event, history, score)
    snapshot, revisions = reconcile(selected, state.get("revisions", {}), now)
    report = {
        "matched": len(selected),
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
        **history_report,
    }
    return (
        snapshot,
        {"profile": profile, "history": history, "revisions": revisions},
        report,
    )


def refresh(store, parameters, http, now, *, preview=False):
    try:
        previous = store.claim()
    except Busy:
        return {"status": "busy"}
    try:
        state, etag = store.read("private.json")
        published_revisions = state.get("revisions", {})
        token = Auth(http, parameters, store).access()
        snapshot, state, report = collect(Zwift(http, token), state, now)
        if preview:
            state["revisions"] = published_revisions
        store.private_write("private.json", state, etag)
        if not preview:
            store.publish(snapshot)
        return {
            "status": "degraded" if report["score_degraded"] else "ok",
            "report": report,
            "changed": snapshot["etag"] != previous.get("etag"),
            **({"ics": snapshot["ics"]} if preview else {}),
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
        if now.timestamp() - data.get("last_success", 0) > 10800:
            raise RuntimeError("Zwift calendar snapshot is older than three hours")
        return {"status": "ok"}
    if event.get("routeKey") != "GET /calendars/zwift.ics":
        return {"statusCode": 404, "body": "Not found"}
    if "ics" not in data:
        return {
            "statusCode": 503,
            "headers": {"Retry-After": "300"},
            "body": "Calendar is initializing",
        }
    headers = {
        "Content-Type": "text/calendar; charset=utf-8",
        "ETag": data["etag"],
        "Cache-Control": "public, max-age=300",
        "Content-Disposition": 'inline; filename="zwift.ics"',
    }
    request = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    tags = [
        s.strip().removeprefix("W/")
        for s in request.get("if-none-match", "").split(",")
    ]
    if "*" in tags or data["etag"] in tags:
        return {"statusCode": 304, "headers": headers, "body": ""}
    return {"statusCode": 200, "headers": headers, "body": data["ics"]}


def feed_handler(event, context):
    return serve(event, Store(), datetime.now(UTC))
