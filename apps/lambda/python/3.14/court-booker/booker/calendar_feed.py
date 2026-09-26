"""Read-only calendar endpoints: one public feed and one key-protected private feed.

Never logs request paths, keys or SDK error text.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import UTC, datetime
from functools import lru_cache

import boto3
from botocore.config import Config

from booker.calendar_ics import render_calendar
from booker.calendar_repository import CalendarRepository, visibility_of
from booker.secrets import _client_kwargs

logger = logging.getLogger(__name__)

CALENDAR_NAMES = {"public": "Court bookings", "private": "Coaching (private)"}
PUBLIC_ROUTE = "GET /calendars/public/bookings.ics"
PRIVATE_ROUTE = "GET /calendars/private/{key}/bookings.ics"
MIN_KEY_LENGTH = 32
UNSET = "UNSET"
# Rotation reaches warm containers within this window.
KEY_CACHE_SECONDS = 300


@lru_cache(maxsize=1)
def _lambda_client():
    return boto3.client(
        "lambda",
        **_client_kwargs(),
        config=Config(
            connect_timeout=3,
            read_timeout=5,
            retries={"total_max_attempts": 2, "mode": "standard"},
        ),
    )


@lru_cache(maxsize=1)
def _ssm_client():
    return boto3.client(
        "ssm",
        **_client_kwargs(),
        config=Config(
            connect_timeout=2,
            read_timeout=3,
            retries={"total_max_attempts": 2, "mode": "standard"},
        ),
    )


_key_cache: dict[str, object] = {}


def _load_private_key_digest(ssm, clock=time.monotonic) -> bytes | None:
    """SHA-256 of the configured private key, or None when unusable (fail closed).

    A usable key is cached per container for KEY_CACHE_SECONDS; failures are not
    cached, so a newly set key takes effect without a redeploy.
    """
    cached = _key_cache.get("digest")
    if cached is not None and clock() < _key_cache["expires"]:
        return cached
    _key_cache.clear()
    name = os.environ.get("CALENDAR_PRIVATE_KEY_PARAMETER", "").strip()
    if not name:
        logger.error("Calendar private key is not configured")
        return None
    try:
        value = ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    except Exception:  # noqa: BLE001 - fail closed; SDK errors may carry request details
        logger.error("Calendar private key could not be loaded")
        return None
    if not isinstance(value, str) or value == UNSET or len(value) < MIN_KEY_LENGTH:
        logger.error("Calendar private key is not configured")
        return None
    digest = hashlib.sha256(value.encode()).digest()
    _key_cache.update(digest=digest, expires=clock() + KEY_CACHE_SECONDS)
    return digest


def _private_key_matches(key, ssm) -> bool:
    if not isinstance(key, str) or not key or len(key) > 256:
        return False
    expected = _load_private_key_digest(ssm)
    if expected is None:
        return False
    return hmac.compare_digest(hashlib.sha256(key.encode()).digest(), expected)


def _response(status: int, body: str = "", **headers: str) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Cache-Control": "private, no-cache",
            "Referrer-Policy": "no-referrer",
            **headers,
        },
        "body": body,
    }


def _request_refresh(repository, client, now):
    lease_id = repository.claim_refresh(now=now)
    if lease_id is None:
        return
    try:
        response = client.invoke(
            FunctionName=os.environ["CALENDAR_RECONCILE_FUNCTION"],
            InvocationType="Event",
            Payload=json.dumps({"lease_id": lease_id}).encode(),
        )
        if response.get("StatusCode") != 202:
            raise RuntimeError("Refresh invocation was not accepted")
    except Exception:  # noqa: BLE001 - preserve the feed and redact invocation errors
        # No exception text: SDK errors can include sensitive request details.
        logger.error("Calendar refresh invocation failed")
        repository.release_refresh(lease_id)


def serve(
    event: dict, repository, client, now: datetime | None = None, ssm=None
) -> dict:
    now = now or datetime.now(UTC)
    route = event.get("routeKey")
    if route == PUBLIC_ROUTE:
        private = False
    elif route == PRIVATE_ROUTE:
        key = (event.get("pathParameters") or {}).get("key")
        if not _private_key_matches(key, ssm if ssm is not None else _ssm_client()):
            return _response(404, "Not found")
        private = True
    else:
        return _response(404, "Not found")
    metadata = repository.get_metadata()
    reservations = [
        item
        for item in (
            repository.list_events(now=now) if metadata.get("initialized") else []
        )
        if visibility_of(item) == ("private" if private else "public")
    ]
    # Snapshot first. A completed async refresh becomes visible on the next poll.
    body = (
        render_calendar(
            reservations, name=CALENDAR_NAMES["private" if private else "public"]
        )
        if metadata.get("initialized")
        else None
    )
    _request_refresh(repository, client, now)
    if body is None:
        return _response(503, "Calendar is initializing", **{"Retry-After": "60"})
    etag = '"' + hashlib.sha256(body).hexdigest() + '"'
    headers = {"Content-Type": "text/calendar; charset=utf-8", "ETag": etag}
    request_headers = {
        key.lower(): value for key, value in (event.get("headers") or {}).items()
    }
    tags = [
        tag.strip().removeprefix("W/")
        for tag in request_headers.get("if-none-match", "").split(",")
    ]
    if etag in tags or "*" in tags:
        return _response(304, **headers)
    return _response(200, body.decode("utf-8"), **headers)


def lambda_handler(event, context):
    return serve(event, CalendarRepository(), _lambda_client())
