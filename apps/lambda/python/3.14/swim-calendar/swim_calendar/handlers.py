"""Atomic S3 publication and a read-only calendar download handler."""
from datetime import UTC, datetime, timedelta
from functools import lru_cache
import hashlib
import json
import os
import uuid
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from swim_calendar.source import Upace, ZONE, month_end
from swim_calendar.calendar import reconcile, render

KEY = "current.json"


@lru_cache
def s3():
    return boto3.client("s3", config=Config(connect_timeout=3, read_timeout=10,
                        retries={"total_max_attempts": 3, "mode": "standard"}))


def load(client, bucket, key=KEY):
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except client.exceptions.NoSuchKey:
        return None, None
    with response["Body"] as body:
        return json.loads(body.read()), response["ETag"]


def publish(client, bucket, source, now, remaining=lambda: 600_000):
    old, etag = load(client, bucket)
    start = now.astimezone(ZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    end = month_end(start.date())
    fresh = source.collect(start.date(), end, remaining)
    events = reconcile((old or {}).get("events", {}), fresh, now, start, end)
    body = render(events)
    snapshot = {"version": 1, "last_success": now.isoformat(), "through_exclusive": str(end),
                "events": events, "ics": body, "etag": '"' + hashlib.sha256(body.encode()).hexdigest() + '"'}
    # Single atomic object holds both revisions and feed: no partial publication.
    # Conditional replacement also fences unexpected concurrent/manual writers.
    client.put_object(Bucket=bucket, Key=KEY, Body=json.dumps(snapshot).encode(),
                      ContentType="application/json", **({"IfMatch": etag} if etag else {"IfNoneMatch": "*"}))
    return {"status": "synced", "events": len(fresh), "through_exclusive": str(end)}


def claim(client, bucket, now):
    old, etag = load(client, bucket, "lease.json")
    if old and old["until"] > now.timestamp():
        return None
    try:
        result = client.put_object(Bucket=bucket, Key="lease.json",
                   Body=json.dumps({"until": now.timestamp() + 660, "token": uuid.uuid4().hex}).encode(),
                   **({"IfMatch": etag} if etag else {"IfNoneMatch": "*"}))
        return result["ETag"]
    except ClientError as error:
        if error.response["Error"]["Code"] in ("PreconditionFailed", "ConditionalRequestConflict"):
            return None
        raise


def release(client, bucket, lease):
    try:
        client.put_object(Bucket=bucket, Key="lease.json", IfMatch=lease,
                          Body=json.dumps({"until": 0, "token": uuid.uuid4().hex}).encode())
    except ClientError as error:
        if error.response["Error"]["Code"] not in ("PreconditionFailed", "ConditionalRequestConflict"):
            raise


def sync(event, context):
    client, bucket = s3(), os.environ["SNAPSHOT_BUCKET"]
    lease = claim(client, bucket, datetime.now(UTC))
    if lease is None:
        return {"status": "busy"}
    source = None
    try:
        source = Upace()
        result = publish(client, bucket, source, datetime.now(UTC),
                         context.get_remaining_time_in_millis)
        print(json.dumps({"_aws": {"Timestamp": int(datetime.now(UTC).timestamp() * 1000),
              "CloudWatchMetrics": [{"Namespace": "SwimCalendar", "Dimensions": [["Service"]],
              "Metrics": [{"Name": "SyncSuccess", "Unit": "Count"}]}]},
              "Service": "swim-calendar", "SyncSuccess": 1, **result}))
        return result
    except Exception:
        raise RuntimeError("Swimming calendar refresh failed; previous snapshot preserved") from None
    finally:
        if source is not None:
            source.close()
        release(client, bucket, lease)


def serve(event, snapshot):
    headers = {"Cache-Control": "public, max-age=300", "Content-Type": "text/calendar; charset=utf-8"}
    if snapshot is None:
        return {"statusCode": 503, "headers": {**headers, "Cache-Control": "no-store", "Retry-After": "60"},
                "body": "Calendar is initializing"}
    headers["ETag"] = snapshot["etag"]
    request = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    tags = [t.strip().removeprefix("W/") for t in request.get("if-none-match", "").split(",")]
    unchanged = snapshot["etag"] in tags or "*" in tags
    return {"statusCode": 304 if unchanged else 200, "headers": headers,
            "body": "" if unchanged else snapshot["ics"]}


def feed(event, context):
    snapshot, _ = load(s3(), os.environ["SNAPSHOT_BUCKET"])
    if event.get("health") is True:
        if snapshot is None or datetime.now(UTC) - datetime.fromisoformat(snapshot["last_success"]) > timedelta(hours=36):
            raise RuntimeError("Swimming calendar has no successful refresh within 36 hours")
        return {"status": "healthy"}
    return serve(event, snapshot)
