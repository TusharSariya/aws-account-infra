from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Protocol

from booker.stub import BookingRequest

PENDING = "PENDING"
SUCCEEDED = "SUCCEEDED"
RECONCILE = "RECONCILE"


def booking_key(request: BookingRequest) -> str:
    return "#".join(
        (
            request.activity_key,
            request.target_date.isoformat(),
            request.hhmm,
            str(request.duration_min),
        )
    )


class IdempotencyStore(Protocol):
    def acquire(self, request: BookingRequest) -> str | None: ...
    def complete(self, request: BookingRequest) -> None: ...
    def reconcile(self, request: BookingRequest, reason: str) -> None: ...
    def release(self, request: BookingRequest) -> None: ...


@dataclass
class DynamoIdempotencyStore:
    table_name: str
    ttl_seconds: int = 60 * 60 * 24 * 30

    def __post_init__(self) -> None:
        import boto3

        self._table = boto3.resource("dynamodb").Table(self.table_name)

    def acquire(self, request: BookingRequest) -> str | None:
        from botocore.exceptions import ClientError

        key = booking_key(request)
        now = int(time.time())
        try:
            self._table.put_item(
                Item={
                    "id": key,
                    "status": PENDING,
                    "created_at": now,
                    "expiration": now + self.ttl_seconds,
                },
                ConditionExpression="attribute_not_exists(id)",
            )
            return None
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
        response = self._table.get_item(Key={"id": key}, ConsistentRead=True)
        return str(response.get("Item", {}).get("status") or PENDING)

    def complete(self, request: BookingRequest) -> None:
        self._set_status(request, SUCCEEDED)

    def reconcile(self, request: BookingRequest, reason: str) -> None:
        self._table.update_item(
            Key={"id": booking_key(request)},
            UpdateExpression="SET #status = :status, reconcile_reason = :reason",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": RECONCILE,
                ":reason": reason[:500],
                ":pending": PENDING,
            },
            ConditionExpression="#status = :pending",
        )

    def release(self, request: BookingRequest) -> None:
        self._table.delete_item(
            Key={"id": booking_key(request)},
            ConditionExpression="#status = :pending",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":pending": PENDING},
        )

    def _set_status(self, request: BookingRequest, status: str) -> None:
        self._table.update_item(
            Key={"id": booking_key(request)},
            UpdateExpression="SET #status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": status},
        )


def store_from_environment() -> IdempotencyStore | None:
    table_name = os.environ.get("IDEMPOTENCY_TABLE", "").strip()
    return DynamoIdempotencyStore(table_name) if table_name else None
