"""Opt-in local storage integration. Deliberately disabled on CI."""

import os
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

import boto3
import pytest

from iracing_calendar.reconcile import reconcile
from iracing_calendar.store import Conflict, Store

ENDPOINT = os.environ.get("IRACING_LOCALSTACK_ENDPOINT", "")
pytestmark = pytest.mark.skipif(
    not ENDPOINT
    or bool(os.environ.get("CI"))
    or bool(os.environ.get("GITHUB_ACTIONS")),
    reason="Local opt-in integration only",
)


def test_s3_conditional_publication_and_lease_recovery():
    assert urlparse(ENDPOINT).hostname in {"localhost", "127.0.0.1"}
    s3 = boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    bucket = "iracing-test-" + uuid.uuid4().hex
    s3.create_bucket(Bucket=bucket)
    s3.put_bucket_versioning(
        Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
    )
    store = Store(s3, bucket, clock=lambda: 1000)
    try:
        old, etag, lease = store.claim()
        with pytest.raises(Conflict):
            store.claim()
        snapshot = reconcile({}, [], [], datetime(2026, 9, 24, tzinfo=UTC))
        store.publish(old | snapshot, etag, lease)
        assert store.read()[0]["ics"] == snapshot["ics"]
        old, etag, lease = store.claim()
        store.clock = lambda: 1601
        recovered, current, owner = store.claim()
        with pytest.raises(Conflict):
            store.publish(old, etag, lease)
        store.publish(recovered, current, owner)
        assert store.read()[0]["ics"] == snapshot["ics"]
    finally:
        for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
            versions = [
                {"Key": v["Key"], "VersionId": v["VersionId"]}
                for v in page.get("Versions", [])
            ]
            if versions:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": versions})
        s3.delete_bucket(Bucket=bucket)
