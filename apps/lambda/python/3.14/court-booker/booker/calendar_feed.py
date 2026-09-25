"""Read-only subscription endpoint; never logs capability URLs or tokens."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from functools import lru_cache

import boto3
from botocore.config import Config

from booker.calendar_ics import render_calendar
from booker.calendar_repository import CalendarRepository, visibility_of
from booker.secrets import _client_kwargs

logger = logging.getLogger(__name__)

CALENDAR_NAMES = {"public": "Court bookings", "private": "Court bookings (private)"}


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


def serve(event: dict, repository, client, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    token = (event.get("pathParameters") or {}).get("token", "")
    scope = (
        repository.validate_token(token) if isinstance(token, str) and token else None
    )
    if not scope:
        return _response(404, "Not found")
    # Anything other than an explicit private scope gets the public view.
    private = scope == "private"
    metadata = repository.get_metadata()
    reservations = [
        item
        for item in (
            repository.list_events(now=now) if metadata.get("initialized") else []
        )
        if private or visibility_of(item) == "public"
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
