"""Atomic publication; enrichment failure never removes PDF fixtures."""

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from squash_calendar.calendar import reconcile, render
from squash_calendar.model import backtest
from squash_calendar.source import ClubLocker, SourceError

KEY = "current.json"


@lru_cache
def s3():
    return boto3.client(
        "s3",
        config=Config(
            connect_timeout=3,
            read_timeout=10,
            retries={"total_max_attempts": 3, "mode": "standard"},
        ),
    )


def load(client, bucket, key=KEY):
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except client.exceptions.NoSuchKey:
        return None, None
    with response["Body"] as body:
        return json.loads(body.read()), response["ETag"]


def publish(client, bucket, source, now):
    old, etag = load(client, bucket)
    old = old or {}
    data, healthy = old.get("enrichment"), False
    try:
        fresh = source.collect(now, data)
        # Avoid repeating an expensive chronological fit unless completed results changed.
        digest = hashlib.sha256(
            json.dumps(fresh["matches"], sort_keys=True).encode()
        ).hexdigest()
        fresh["backtest"] = (
            data["backtest"]
            if data and data.get("matches_digest") == digest
            else backtest(fresh["matches"])
        )
        fresh["matches_digest"] = digest
        data, healthy = fresh, True
    except SourceError:
        pass  # Expected source outage: retain original as-of, publish authoritative schedule.
    events = reconcile(old.get("events", {}), data if healthy else None, now)
    snapshot = {
        "version": 1,
        "last_success": now.isoformat(),
        "enrichment_ok": healthy,
        "enrichment": data,
        "events": events,
    }
    client.put_object(
        Bucket=bucket,
        Key=KEY,
        Body=json.dumps(snapshot).encode(),
        ContentType="application/json",
        **({"IfMatch": etag} if etag else {"IfNoneMatch": "*"}),
    )
    return {
        "status": "synced",
        "events": sum(e["status"] != "CANCELLED" for e in events.values()),
        "enrichment_ok": healthy,
        "matches": len(data["matches"]) if data else 0,
    }


def claim(client, bucket, now):
    old, etag = load(client, bucket, "lease.json")
    if old and old["until"] > now.timestamp():
        return None
    try:
        result = client.put_object(
            Bucket=bucket,
            Key="lease.json",
            Body=json.dumps(
                {"until": now.timestamp() + 660, "token": uuid.uuid4().hex}
            ).encode(),
            **({"IfMatch": etag} if etag else {"IfNoneMatch": "*"}),
        )
        return result["ETag"]
    except ClientError as error:
        if error.response["Error"]["Code"] in (
            "PreconditionFailed",
            "ConditionalRequestConflict",
        ):
            return None
        raise


def release(client, bucket, lease):
    try:
        client.put_object(
            Bucket=bucket,
            Key="lease.json",
            IfMatch=lease,
            Body=json.dumps({"until": 0, "token": uuid.uuid4().hex}).encode(),
        )
    except ClientError as error:
        if error.response["Error"]["Code"] not in (
            "PreconditionFailed",
            "ConditionalRequestConflict",
        ):
            raise


def sync(event, context):
    client, bucket = s3(), os.environ["SNAPSHOT_BUCKET"]
    lease = claim(client, bucket, datetime.now(UTC))
    if lease is None:
        return {"status": "busy"}
    source = ClubLocker(remaining=context.get_remaining_time_in_millis)
    try:
        result = publish(client, bucket, source, datetime.now(UTC))
        # Separate source health from schedule publication; only safe aggregate logs.
        print(
            json.dumps(
                {
                    "_aws": {
                        "Timestamp": int(datetime.now(UTC).timestamp() * 1000),
                        "CloudWatchMetrics": [
                            {
                                "Namespace": "SquashCalendar",
                                "Dimensions": [["Service"]],
                                "Metrics": [
                                    {"Name": "EnrichmentFailure", "Unit": "Count"}
                                ],
                            }
                        ],
                    },
                    "Service": "squash-calendar",
                    "EnrichmentFailure": int(not result["enrichment_ok"]),
                    **result,
                }
            )
        )
        return result
    except Exception:  # noqa: BLE001 - sanitize unexpected upstream/SDK errors at Lambda boundary
        raise RuntimeError(
            "Squash refresh failed; previous snapshot retained"
        ) from None
    finally:
        source.close()
        release(client, bucket, lease)


def serve(event, snapshot, now=None):
    now = now or datetime.now(UTC)
    headers = {
        "Cache-Control": "public, max-age=300",
        "Content-Type": "text/calendar; charset=utf-8",
        "Content-Disposition": 'attachment; filename="tushar-asc-squash.ics"',
    }
    if snapshot is None:
        return {
            "statusCode": 503,
            "headers": {**headers, "Cache-Control": "no-store", "Retry-After": "60"},
            "body": "Calendar is initializing",
        }
    # Rendering at download time enforces the 48-hour freshness limit even if sync stops.
    body = render(snapshot["events"], now)
    etag = '"' + hashlib.sha256(body.encode()).hexdigest() + '"'
    headers["ETag"] = etag
    request = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    tags = [
        t.strip().removeprefix("W/")
        for t in request.get("if-none-match", "").split(",")
    ]
    unchanged = etag in tags or "*" in tags
    return {
        "statusCode": 304 if unchanged else 200,
        "headers": headers,
        "body": "" if unchanged else body,
    }


def feed(event, context):
    snapshot, _ = load(s3(), os.environ["SNAPSHOT_BUCKET"])
    if event.get("health") is True:
        now = datetime.now(UTC)
        if snapshot is None or now - datetime.fromisoformat(
            snapshot["last_success"]
        ) > timedelta(hours=36):
            raise RuntimeError("Squash schedule has not refreshed within 36 hours")
        data = snapshot.get("enrichment")
        if not data or now - datetime.fromisoformat(data["as_of"]) > timedelta(
            hours=48
        ):
            raise RuntimeError("Squash enrichment has not refreshed within 48 hours")
        return {"status": "healthy"}
    return serve(event, snapshot)
