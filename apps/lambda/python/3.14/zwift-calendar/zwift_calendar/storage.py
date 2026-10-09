"""Conditional S3 publication and a lease shared by sync and token renewal."""

import json
import os
import time
import uuid

import boto3
from botocore.config import Config

CONFIG = Config(
    connect_timeout=3,
    read_timeout=10,
    retries={"total_max_attempts": 3, "mode": "standard"},
)


def client(service):
    # A synchronous Lambda refresh can run for 540 seconds. Replaying an invoke
    # on a short read timeout only encounters its own still-active lease.
    config = (
        CONFIG.merge(Config(read_timeout=600, retries={"total_max_attempts": 1}))
        if service == "lambda"
        else CONFIG
    )
    return boto3.client(service, config=config)


class Busy(RuntimeError):
    pass


class Store:
    def __init__(self, bucket=None, s3=None, clock=time.time):
        self.bucket = bucket or os.environ["SNAPSHOT_BUCKET"]
        self.s3 = s3 or client("s3")
        self.clock = clock
        self.owner = self.etag = None

    def read(self, key="current.json"):
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
        except self.s3.exceptions.NoSuchKey:
            return {}, None
        with response["Body"] as body:
            return json.load(body), response["ETag"]

    def write(self, key, data, etag):
        try:
            response = self.s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=json.dumps(data, sort_keys=True, separators=(",", ":")).encode(),
                ContentType="application/json",
                **({"IfMatch": etag} if etag else {"IfNoneMatch": "*"}),
            )
        except self.s3.exceptions.ClientError as exc:
            if exc.response["ResponseMetadata"]["HTTPStatusCode"] in (409, 412):
                raise Busy("Concurrent calendar update") from None
            raise
        return response["ETag"]

    def claim(self):
        data, etag = self.read()
        if data.get("lease_until", 0) > self.clock():
            raise Busy("Calendar sync already running")
        self.owner = uuid.uuid4().hex
        self.etag = self.write(
            "current.json",
            data | {"lease": self.owner, "lease_until": self.clock() + 600},
            etag,
        )
        return data

    def fence(self):
        data, etag = self.read()
        if (
            etag != self.etag
            or data.get("lease") != self.owner
            or data.get("lease_until", 0) <= self.clock() + 30
        ):
            raise Busy("Calendar lease expired")

    def private_write(self, key, data, etag):
        self.fence()
        return self.write(key, data, etag)

    def publish(self, snapshot):
        self.fence()
        self.write("current.json", snapshot, self.etag)

    def release(self):
        data, etag = self.read()
        if etag == self.etag and data.get("lease") == self.owner:
            try:
                self.write(
                    "current.json",
                    {
                        k: v
                        for k, v in data.items()
                        if k not in ("lease", "lease_until")
                    },
                    etag,
                )
            except Busy:
                pass


class Parameters:
    def __init__(self, ssm=None):
        self.ssm = ssm or client("ssm")

    def read(self, name, *, missing=False):
        try:
            raw = self.ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"][
                "Value"
            ]
        except self.ssm.exceptions.ParameterNotFound:
            if missing:
                return {}
            raise
        return json.loads(raw)

    def write(self, name, value):
        raw = json.dumps(value, separators=(",", ":"))
        if len(raw.encode()) > 4096:
            raise ValueError("Authentication parameter exceeds Standard tier limit")
        self.ssm.put_parameter(
            Name=name,
            Value=raw,
            Type="SecureString",
            KeyId="alias/aws/ssm",
            Tier="Standard",
            Overwrite=True,
        )
