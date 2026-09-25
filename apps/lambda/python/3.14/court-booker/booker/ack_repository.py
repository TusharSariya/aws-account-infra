"""Friend acknowledgement state for one booked court; every transition is conditional.

Items (table ACK_TABLE, string PK/SK, TTL on `expires_at`):
  BOOKING#<id> / META          window state, quorum counter and Step Functions task token
  BOOKING#<id> / INVITEE#<iid> one friend (or the owner) and their answer
  TOKEN#<sha256> / TOKEN       capability lookup; only the hash of a link token is stored
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.config import Config
from botocore.exceptions import ClientError

from booker.secrets import _client_kwargs

logger = logging.getLogger(__name__)

PENDING = "PENDING"
CONFIRMED = "CONFIRMED"
EXPIRED = "EXPIRED"
CANCELLED = "CANCELLED"
CANCEL_FAILED = "CANCEL_FAILED"
FRIEND = "friend"
OWNER = "owner"
ACCEPT = "accept"
DECLINE = "decline"
TOKEN_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)
# A task that is already closed cannot be completed again; Expire re-reads state.
IGNORED_CALLBACK_ERRORS = {"TaskTimedOut", "TaskDoesNotExist", "InvalidToken"}


def utcnow(now=None) -> datetime:
    if isinstance(now, (int, float)):
        return datetime.fromtimestamp(now, UTC)
    return (now or datetime.now(UTC)).astimezone(UTC)


def iso(value: datetime) -> str:
    """Fixed-width UTC timestamp, so DynamoDB string comparison orders correctly."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def invitee_id_for(role: str, email: str) -> str:
    """Stable across retries and roster reordering, without putting addresses in keys."""
    if role == OWNER:
        return OWNER
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:20]


def booking_key(reservation_id: str) -> dict:
    return {"PK": "BOOKING#" + str(reservation_id), "SK": "META"}


def invitee_key(reservation_id: str, invitee_id: str) -> dict:
    return {"PK": "BOOKING#" + str(reservation_id), "SK": "INVITEE#" + invitee_id}


def token_key(token_hash: str) -> dict:
    return {"PK": "TOKEN#" + token_hash, "SK": "TOKEN"}


@dataclass(frozen=True)
class Response:
    """Outcome of one POST: accepted, confirmed, kept, declined, already_answered, full, closed."""

    outcome: str
    meta: dict = field(default_factory=dict)
    invitee: dict = field(default_factory=dict)


class AckRepository:
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
            ).Table(os.environ["ACK_TABLE"])
        )
        self._errors = self.table.meta.client.exceptions

    def _get(self, key) -> dict:
        return self.table.get_item(Key=key, ConsistentRead=True).get("Item", {})

    def get_meta(self, reservation_id: str) -> dict:
        return self._get(booking_key(reservation_id))

    def get_invitee(self, reservation_id: str, invitee_id: str) -> dict:
        return self._get(invitee_key(reservation_id, invitee_id))

    def list_invitees(self, reservation_id: str) -> list[dict]:
        paginator = self.table.meta.client.get_paginator("query")
        items: list[dict] = []
        for page in paginator.paginate(
            TableName=self.table.name,
            KeyConditionExpression=Key("PK").eq("BOOKING#" + str(reservation_id))
            & Key("SK").begins_with("INVITEE#"),
            ConsistentRead=True,
        ):
            items.extend(page.get("Items", []))
        return items

    def _transact(self, items: list[dict]) -> bool:
        """False when a condition failed; other cancellation reasons propagate."""
        try:
            self.table.meta.client.transact_write_items(TransactItems=items)
        except self._errors.TransactionCanceledException as exc:
            reasons = exc.response.get("CancellationReasons", [])
            if not reasons or any(
                r.get("Code") not in ("None", "ConditionalCheckFailed") for r in reasons
            ):
                raise
            return False
        return True

    def create_window(self, reservation_id: str, fields: dict) -> tuple[dict, bool]:
        """Insert META once. Retries return the stored window unchanged."""
        item = {
            **booking_key(reservation_id),
            **fields,
            "reservation_id": str(reservation_id),
            "state": PENDING,
            "ack_count": 0,
        }
        try:
            self.table.put_item(Item=item, ConditionExpression=Attr("PK").not_exists())
        except self._errors.ConditionalCheckFailedException:
            return self.get_meta(reservation_id), False
        return item, True

    def store_task_token(self, reservation_id: str, task_token: str) -> dict:
        """Always keep the newest token: a retried wait task gets a fresh one."""
        return self.table.update_item(
            Key=booking_key(reservation_id),
            UpdateExpression="SET task_token = :t",
            ExpressionAttributeValues={":t": task_token},
            ConditionExpression=Attr("PK").exists(),
            ReturnValues="ALL_NEW",
        )["Attributes"]

    def issue_invite(
        self,
        reservation_id: str,
        *,
        role: str,
        name: str,
        email: str,
        expires_at: int,
    ) -> str | None:
        """Return a new link token for an unsent invite, or None when already sent.

        Only the hash is stored, so an invite whose email never went out gets a
        fresh token instead of a resend. The unsent token's lookup item is left to
        TTL; resolve_token rejects it because the invitee now holds a new hash.
        """
        iid = invitee_id_for(role, email)
        key = invitee_key(reservation_id, iid)
        current = self._get(key)
        if current.get("sent_at") or current.get("response"):
            return None
        token = secrets.token_urlsafe(32)
        digest = hash_token(token)
        items = [
            {
                "Put": {
                    "TableName": self.table.name,
                    "Item": {
                        **key,
                        "invitee_id": iid,
                        "role": role,
                        "name": name,
                        "email": email,
                        "token_hash": digest,
                        "expires_at": expires_at,
                    },
                    "ConditionExpression": "attribute_not_exists(sent_at) "
                    "AND attribute_not_exists(#r)",
                    "ExpressionAttributeNames": {"#r": "response"},
                }
            },
            {
                "Put": {
                    "TableName": self.table.name,
                    "Item": {
                        **token_key(digest),
                        "reservation_id": str(reservation_id),
                        "invitee_id": iid,
                        "expires_at": expires_at,
                    },
                    "ConditionExpression": "attribute_not_exists(PK)",
                }
            },
        ]
        if self._transact(items):
            return token
        latest = self._get(key)
        if latest.get("sent_at") or latest.get("response"):
            return None
        raise RuntimeError("invite changed concurrently")

    def mark_sent(self, reservation_id: str, invitee_id: str, now=None) -> None:
        try:
            self.table.update_item(
                Key=invitee_key(reservation_id, invitee_id),
                UpdateExpression="SET sent_at = :now",
                ExpressionAttributeValues={":now": iso(utcnow(now))},
                ConditionExpression=Attr("PK").exists() & Attr("sent_at").not_exists(),
            )
        except self._errors.ConditionalCheckFailedException:
            pass

    def resolve_token(self, token, now=None) -> tuple[dict, dict] | None:
        """(meta, invitee) for a live link token, else None. Constant work per lookup."""
        if (
            not isinstance(token, str)
            or not 20 <= len(token) <= 128
            or not set(token) <= TOKEN_CHARS
        ):
            return None
        digest = hash_token(token)
        record = self._get(token_key(digest))
        if not record or int(record.get("expires_at", 0)) <= int(utcnow(now).timestamp()):
            return None
        invitee = self.get_invitee(record["reservation_id"], record["invitee_id"])
        if not invitee or not hmac.compare_digest(
            str(invitee.get("token_hash", "")), digest
        ):
            return None
        meta = self.get_meta(record["reservation_id"])
        if not meta:
            return None
        return meta, invitee

    def respond(
        self, reservation_id: str, invitee_id: str, response: str, now=None
    ) -> Response:
        if response not in (ACCEPT, DECLINE):
            raise ValueError("response must be accept or decline")
        now_iso = iso(utcnow(now))
        for _ in range(8):
            meta = self.get_meta(reservation_id)
            invitee = self.get_invitee(reservation_id, invitee_id)
            if not meta or not invitee:
                raise LookupError("unknown invite")
            owner = invitee.get("role") == OWNER
            if invitee.get("response"):
                return Response("already_answered", meta, invitee)
            if meta["state"] == CONFIRMED:
                return Response("full", meta, invitee)
            # The owner may keep the court until Expire runs; friends stop at the deadline.
            if meta["state"] != PENDING or (not owner and meta["deadline"] <= now_iso):
                return Response("closed", meta, invitee)
            answer = {
                "Update": {
                    "TableName": self.table.name,
                    "Key": invitee_key(reservation_id, invitee_id),
                    "UpdateExpression": "SET #r = :r, responded_at = :now",
                    "ConditionExpression": "attribute_exists(PK) AND attribute_not_exists(#r)",
                    "ExpressionAttributeNames": {"#r": "response"},
                    "ExpressionAttributeValues": {":r": response, ":now": now_iso},
                }
            }
            names = {"#s": "state"}
            if response == DECLINE:
                window = {
                    "ConditionCheck": {
                        "TableName": self.table.name,
                        "Key": booking_key(reservation_id),
                        "ConditionExpression": "#s = :pending"
                        + ("" if owner else " AND deadline > :now"),
                        "ExpressionAttributeNames": names,
                        "ExpressionAttributeValues": {":pending": PENDING}
                        | ({} if owner else {":now": now_iso}),
                    }
                }
                outcome = "declined"
            elif owner:
                window = {
                    "Update": {
                        "TableName": self.table.name,
                        "Key": booking_key(reservation_id),
                        "UpdateExpression": "SET #s = :confirmed, outcome = :kept, confirmed_at = :now",
                        "ConditionExpression": "#s = :pending",
                        "ExpressionAttributeNames": names,
                        "ExpressionAttributeValues": {
                            ":pending": PENDING,
                            ":confirmed": CONFIRMED,
                            ":kept": "kept",
                            ":now": now_iso,
                        },
                    }
                }
                outcome = "kept"
            else:
                seen = int(meta.get("ack_count", 0))
                reached = seen + 1 >= int(meta["required"])
                values = {
                    ":pending": PENDING,
                    ":now": now_iso,
                    ":seen": seen,
                    ":next": seen + 1,
                }
                update = "SET ack_count = :next"
                if reached:
                    update += ", #s = :confirmed, outcome = :outcome, confirmed_at = :now"
                    values |= {":confirmed": CONFIRMED, ":outcome": "confirmed"}
                window = {
                    "Update": {
                        "TableName": self.table.name,
                        "Key": booking_key(reservation_id),
                        "UpdateExpression": update,
                        "ConditionExpression": "#s = :pending AND deadline > :now AND ack_count = :seen",
                        "ExpressionAttributeNames": names,
                        "ExpressionAttributeValues": values,
                    }
                }
                outcome = "confirmed" if reached else "accepted"
            if self._transact([answer, window]):
                return Response(
                    outcome,
                    self.get_meta(reservation_id),
                    self.get_invitee(reservation_id, invitee_id),
                )
            # Lost a race (double click, concurrent accept or Expire): re-read and decide.
        raise RuntimeError("acknowledgement write contention")

    def expire(self, reservation_id: str, now=None) -> dict:
        """PENDING -> EXPIRED. Returns the resulting META (state tells who won)."""
        try:
            return self.table.update_item(
                Key=booking_key(reservation_id),
                UpdateExpression="SET #s = :expired, expired_at = :now",
                ConditionExpression="#s = :pending",
                ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues={
                    ":pending": PENDING,
                    ":expired": EXPIRED,
                    ":now": iso(utcnow(now)),
                },
                ReturnValues="ALL_NEW",
            )["Attributes"]
        except self._errors.ConditionalCheckFailedException:
            meta = self.get_meta(reservation_id)
            if not meta:
                raise LookupError("unknown acknowledgement window") from None
            return meta

    def finish(self, reservation_id: str, state: str, now=None) -> bool:
        """EXPIRED -> CANCELLED or CANCEL_FAILED; repeating the same transition is a no-op."""
        if state not in (CANCELLED, CANCEL_FAILED):
            raise ValueError("finish only records cancellation outcomes")
        try:
            self.table.update_item(
                Key=booking_key(reservation_id),
                UpdateExpression="SET #s = :state, finished_at = :now",
                ConditionExpression="#s IN (:expired, :state)",
                ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues={
                    ":expired": EXPIRED,
                    ":state": state,
                    ":now": iso(utcnow(now)),
                },
            )
        except self._errors.ConditionalCheckFailedException:
            return False
        return True


@lru_cache(maxsize=1)
def sfn_client():
    return boto3.client(
        "stepfunctions",
        config=Config(
            connect_timeout=2,
            read_timeout=5,
            retries={"mode": "standard", "total_max_attempts": 3},
        ),
        **_client_kwargs(),
    )


def send_task_success(client, task_token: str | None, outcome: str) -> bool:
    """Resume the ack state machine. A closed task is fine: Expire re-reads META."""
    if not task_token:
        logger.warning("ack callback skipped: no task token stored")
        return False
    try:
        client.send_task_success(
            taskToken=task_token, output=json.dumps({"outcome": outcome})
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code not in IGNORED_CALLBACK_ERRORS:
            raise
        # Never log the token or SDK message text.
        logger.info("ack callback ignored: %s", code)
        return False
    return True
