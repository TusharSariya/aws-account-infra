"""One shared calendar, optimistic reservation versions and expiring refresh leases."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.config import Config

from booker.secrets import _client_kwargs

FIELDS = (
    "reservation_id",
    "equipment_id",
    "start",
    "end",
    "court",
    "location",
    "status",
)
META = {"PK": "CALENDAR", "SK": "META"}
LEASE_SECONDS = 240


def utcnow(now=None):
    if isinstance(now, (int, float)):
        return datetime.fromtimestamp(now, UTC)
    return (now or datetime.now(UTC)).astimezone(UTC)


class LeaseLost(RuntimeError):
    pass


class CalendarRepository:
    def __init__(self, table=None):
        self.table = (
            table
            if table is not None
            else boto3.resource(
                "dynamodb",
                config=Config(
                    connect_timeout=2,
                    read_timeout=3,
                    retries={"mode": "standard", "total_max_attempts": 2},
                ),
                **_client_kwargs(),
            ).Table(os.environ["CALENDAR_TABLE"])
        )

    @classmethod
    def from_env(cls):
        return cls()

    def _get(self, key):
        return self.table.get_item(Key=key, ConsistentRead=True).get("Item", {})

    def _query(self, partition, prefix=""):
        paginator = self.table.meta.client.get_paginator("query")
        for page in paginator.paginate(
            TableName=self.table.name,
            KeyConditionExpression=(
                Key("PK").eq(partition) & Key("SK").begins_with(prefix)
                if prefix
                else Key("PK").eq(partition)
            ),
            ConsistentRead=True,
        ):
            yield from page.get("Items", [])

    def get_metadata(self):
        return self._get(META)

    def snapshot(self):
        return {r["reservation_id"]: r for r in self._query("CALENDAR", "RES#")}

    def list_events(self, now=None, include_cancelled=False):
        cutoff = utcnow(now) - timedelta(days=30)
        return [
            r
            for r in self.snapshot().values()
            if datetime.fromisoformat(r["end"]) >= cutoff
            and (include_cancelled or r["status"] == "confirmed")
        ]

    def claim_refresh(self, now=None, force=False):
        epoch = int(utcnow(now).timestamp())
        lease = uuid.uuid4().hex
        condition = Attr("lease_until").not_exists() | Attr("lease_until").lte(epoch)
        if not force:
            condition &= Attr("last_success").not_exists() | Attr("last_success").lte(
                epoch - 900
            )
        try:
            self.table.update_item(
                Key=META,
                UpdateExpression="SET lease_id = :id, lease_until = :until",
                ExpressionAttributeValues={
                    ":id": lease,
                    ":until": epoch + LEASE_SECONDS,
                },
                ConditionExpression=condition,
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return None
        return lease

    def release_refresh(self, lease_id):
        try:
            self.table.update_item(
                Key=META,
                UpdateExpression="REMOVE lease_id, lease_until",
                ConditionExpression=Attr("lease_id").eq(lease_id),
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return False
        return True

    def finish_refresh(self, lease_id, now=None):
        epoch = int(utcnow(now).timestamp())
        try:
            self.table.update_item(
                Key=META,
                UpdateExpression="SET initialized = :yes, last_success = :now REMOVE lease_id, lease_until",
                ExpressionAttributeValues={":yes": True, ":now": epoch},
                ConditionExpression=Attr("lease_id").eq(lease_id)
                & Attr("lease_until").gt(epoch),
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            raise LeaseLost("calendar refresh lease expired") from None
        return True

    def assert_lease(self, lease_id, now=None):
        meta = self.get_metadata()
        if meta.get("lease_id") != lease_id or meta.get("lease_until", 0) <= int(
            utcnow(now).timestamp()
        ):
            raise LeaseLost("calendar refresh lease expired")

    def put_reservation(
        self, reservation, *, expected_version=None, lease_id=None, now=None
    ):
        """Booking writes retry conflicts; reconciliation skips records changed since snapshot."""
        key = {"PK": "CALENDAR", "SK": "RES#" + reservation["reservation_id"]}
        for _ in range(8):
            old = self._get(key)
            if lease_id and old.get("version") != expected_version:
                return False
            changed = any(old.get(k) != reservation[k] for k in FIELDS)
            timestamp = utcnow(now).isoformat()
            item = {
                **key,
                **{k: reservation[k] for k in FIELDS},
                "version": uuid.uuid4().hex,
                "sequence": int(old.get("sequence", -1)) + int(changed),
                "created_at": old.get("created_at", timestamp),
                "updated_at": timestamp if changed else old["updated_at"],
            }
            if lease_id:
                # Transactions fence every reconciliation mutation against the lease
                # and the reservation version, including absent snapshot records.
                put = {
                    "TableName": self.table.name,
                    "Item": item,
                    "ConditionExpression": "attribute_not_exists(#v)"
                    if not old
                    else "#v = :v",
                    "ExpressionAttributeNames": {"#v": "version"},
                }
                if old:
                    put["ExpressionAttributeValues"] = {":v": old["version"]}
                try:
                    self.table.meta.client.transact_write_items(
                        TransactItems=[
                            {
                                "ConditionCheck": {
                                    "TableName": self.table.name,
                                    "Key": META,
                                    "ConditionExpression": "lease_id = :lease AND lease_until > :now",
                                    "ExpressionAttributeValues": {
                                        ":lease": lease_id,
                                        ":now": int(utcnow(now).timestamp()),
                                    },
                                }
                            },
                            {"Put": put},
                        ]
                    )
                    return changed
                except (
                    self.table.meta.client.exceptions.TransactionCanceledException
                ) as exc:
                    reasons = exc.response.get("CancellationReasons", [])
                    if not reasons or any(
                        r.get("Code") not in ("None", "ConditionalCheckFailed")
                        for r in reasons
                    ):
                        raise
                    self.assert_lease(lease_id, now)
                    return False
            try:
                self.table.put_item(
                    Item=item,
                    ConditionExpression=(
                        Attr("version").eq(old["version"])
                        if old
                        else Attr("version").not_exists()
                    ),
                )
                return changed
            except self.table.meta.client.exceptions.ConditionalCheckFailedException:
                continue
        raise RuntimeError("calendar reservation write contention")

    def create_subscription(self, label, now=None):
        if not isinstance(label, str) or not label.strip() or len(label) > 200:
            raise ValueError("subscription label must contain 1 to 200 characters")
        subscription_id = uuid.uuid4().hex
        token = subscription_id + "." + secrets.token_urlsafe(32)
        item = {
            "PK": "SUBSCRIPTIONS",
            "SK": subscription_id,
            "id": subscription_id,
            "label": label.strip(),
            "created_at": utcnow(now).isoformat(),
            "revoked": False,
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        }
        self.table.put_item(Item=item, ConditionExpression=Attr("PK").not_exists())
        return {k: item[k] for k in ("id", "label", "created_at")} | {"token": token}

    def validate_token(self, token):
        if not isinstance(token, str) or len(token) > 256:
            return False
        parts = token.split(".")
        if (
            len(parts) != 2
            or len(parts[0]) != 32
            or not all(c in "0123456789abcdef" for c in parts[0])
        ):
            return False
        item = self._get({"PK": "SUBSCRIPTIONS", "SK": parts[0]})
        return bool(
            item
            and not item.get("revoked")
            and hmac.compare_digest(
                item["token_hash"], hashlib.sha256(token.encode()).hexdigest()
            )
        )

    def list_subscriptions(self):
        return [
            {k: r[k] for k in ("id", "label", "created_at", "revoked")}
            for r in self._query("SUBSCRIPTIONS")
        ]

    def revoke_subscription(self, subscription_id):
        try:
            self.table.update_item(
                Key={"PK": "SUBSCRIPTIONS", "SK": subscription_id},
                UpdateExpression="SET revoked = :yes",
                ExpressionAttributeValues={":yes": True},
                ConditionExpression=Attr("PK").exists(),
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return False
        return True
