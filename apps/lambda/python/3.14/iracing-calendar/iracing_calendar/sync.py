"""API reconciliation, local preview and serialized hourly authentication."""

import json
import logging
import os
from datetime import UTC, datetime

from .adapter import extract
from .api import DataAPI
from .auth import Auth, Parameters
from .catalog import load_catalog
from .migration import differences, migrate
from .reconcile import reconcile
from .sources import Fetcher
from .store import Conflict, Store

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def health(store, now):
    data, _ = store.read()
    age = now.timestamp() - data.get("last_success", 0)
    status = {"age_seconds": age, "report": data.get("report", {})}
    log.info("iRacing calendar health: %s", json.dumps(status))
    if age > int(os.environ.get("HEALTH_THRESHOLD_SECONDS", "86400")):
        raise RuntimeError(
            "iRacing calendar snapshot exceeds configured freshness threshold"
        )
    return status


def authentication(store, etag, owner):
    return Auth(
        Parameters(
            os.environ["IRACING_CLIENT_PARAMETER"],
            os.environ["IRACING_TOKEN_PARAMETER"],
        ),
        store,
        etag,
        owner,
    )


def collect(store, etag, owner, previous, now):
    auth = authentication(store, etag, owner)
    access = auth.access()
    cached, cache_etag = store.read("source-cache.json")
    api = DataAPI(access, cached.get("api", {}))
    web = Fetcher(cached.get("web", {}))
    events, coverage, report = extract(api, load_catalog(now.year), web, now, previous)
    auth.fence()
    store.write({"api": api.used, "web": web.used}, cache_etag, "source-cache.json")
    return events, coverage, report


def refresh(store, now, extractor=collect, preview=False):
    try:
        previous, etag, owner = store.claim()
    except Conflict:
        return {"status": "busy"}
    try:
        incoming, coverage, source_report = extractor(store, etag, owner, previous, now)
        incoming, coverage, mapping = migrate(previous, incoming, coverage)
        snapshot = reconcile(previous, incoming, coverage, now)
        snapshot["uid_migration"] = mapping
        snapshot["report"]["sources"] = source_report
        snapshot["report"]["preview"] = differences(previous, snapshot)
        for warning in source_report.get("identity_warnings", []):
            log.warning("iRacing identity review: %s", json.dumps(warning))
        if snapshot["report"]["retained_unverified_ids"]:
            log.warning(
                "iRacing retained unverified events: %s",
                json.dumps(snapshot["report"]["retained_unverified_ids"]),
            )
        if preview:
            return snapshot
        store.publish(previous | snapshot, etag, owner)
        log.info(
            "iRacing calendar refreshed: %s",
            json.dumps({k: v for k, v in snapshot["report"].items() if k != "preview"}),
        )
        return {"status": "ok", **snapshot["report"]}
    finally:
        store.release(etag, owner)


def lambda_handler(event, context):
    now, store = datetime.now(UTC), Store()
    if event.get("action") == "auth":
        try:
            _, etag, owner = store.claim()
        except Conflict:
            return {"status": "busy"}
        try:
            authentication(store, etag, owner).access()
            return {"status": "ok"}
        finally:
            store.release(etag, owner)
    if event.get("action") == "health":
        return health(store, now)
    return refresh(store, now)
