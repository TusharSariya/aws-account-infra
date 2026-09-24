"""One conditional S3 object fences both lease ownership and atomic publication."""

from __future__ import annotations

import json
import os
import time
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

CONFIG = Config(
    connect_timeout=3,
    read_timeout=10,
    retries={"mode": "standard", "total_max_attempts": 3},
)


def client(service):
    return boto3.client(service, config=CONFIG)


class Conflict(RuntimeError):
    pass


class Store:
    def __init__(self, s3=None, bucket=None, clock=time.time):
        self.s3 = s3 or client("s3")
        self.bucket = bucket or os.environ["SNAPSHOT_BUCKET"]
        self.clock = clock

    def read(self, key="current.json"):
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
        except self.s3.exceptions.NoSuchKey:
            return {}, None
        with response["Body"] as stream:
            return json.load(stream), response["ETag"]

    def write(self, data, etag=None, key="current.json"):
        condition = {"IfMatch": etag} if etag else {"IfNoneMatch": "*"}
        try:
            response = self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=json.dumps(data, sort_keys=True, separators=(",", ":")).encode(),
                ContentType="application/json",
                **condition,
            )
        except ClientError as exc:
            # S3 conditional write races have two documented status codes.
            if exc.response["ResponseMetadata"]["HTTPStatusCode"] in (409, 412):
                raise Conflict("Snapshot changed concurrently") from exc
            raise
        return response["ETag"]

    def claim(self):
        data, etag = self.read()
        now = self.clock()
        if data.get("lease_until", 0) > now:
            raise Conflict("Reconciliation already running")
        owner = uuid.uuid4().hex
        data.update(lease=owner, lease_until=now + 600)
        return data, self.write(data, etag), owner

    def publish(self, data, etag, owner):
        if data.get("lease") != owner or data.get("lease_until", 0) <= self.clock():
            raise Conflict("Reconciliation lease expired")
        self.write(
            {k: v for k, v in data.items() if k not in ("lease", "lease_until")}, etag
        )

    def release(self, etag, owner):
        data, current = self.read()
        if current != etag or data.get("lease") != owner:
            return
        try:
            self.publish(data, etag, owner)
        except Conflict:
            pass
