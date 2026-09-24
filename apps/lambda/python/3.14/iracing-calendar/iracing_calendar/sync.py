"""Scheduled refresh and source-free hourly health checks."""

import json
import logging
import os
from datetime import UTC, datetime

from .reconcile import reconcile
from .sources import Fetcher, extract
from .store import Conflict, Store

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def health(store, now):
    data, _ = store.read()
    age = now.timestamp() - data.get("last_success", 0)
    report = data.get("report", {}) | {
        "upcoming": sum(
            e["start"][:10] >= now.date().isoformat() for e in data.get("events", [])
        )
    }
    status = {"age_seconds": age, "report": report}
    log.info("iRacing calendar health: %s", json.dumps(status))
    if age > int(os.environ.get("HEALTH_THRESHOLD_SECONDS", "691200")):
        raise RuntimeError(
            "iRacing calendar has no successful refresh within eight days"
        )
    return status


def refresh(store, now, extractor=extract):
    try:
        previous, etag, token = store.claim()
    except Conflict:
        return {"status": "busy"}
    try:
        cache, cache_etag = store.read("source-cache.json")
        fetch = Fetcher(cache)
        saved = {
            tuple(key.split("|", 1)): value
            for key, value in previous.get("weekly_overrides", {}).items()
        }
        incoming, coverage, overrides = extractor(fetch, saved)
        next_snapshot = reconcile(previous, incoming, coverage, now)
        next_snapshot["weekly_overrides"] = {
            "|".join(key): value for key, value in overrides.items()
        }
        # Cache writes are not publications; any failure leaves the previous feed intact.
        store.write(fetch.used, cache_etag, "source-cache.json")
        store.publish(previous | next_snapshot, etag, token)
        log.info("iRacing reconciliation: %s", json.dumps(next_snapshot["report"]))
        return {"status": "ok", **next_snapshot["report"]}
    except Exception:
        store.release(etag, token)
        raise


def lambda_handler(event, context):
    now = datetime.now(UTC)
    store = Store()
    if event.get("action") == "health":
        return health(store, now)
    return refresh(store, now)
