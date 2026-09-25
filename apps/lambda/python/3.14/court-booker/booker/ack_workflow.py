"""Ack state machine steps: prepare, send_invites, expire, notify.

Every step is safe to retry: META is written once, invites are emailed at most once
per invitee (sent_at), and state transitions are conditional. Notification emails may
repeat on retry. Logs carry reservation ids and counts only, never tokens or addresses.
"""

from __future__ import annotations

import html
import logging
import math
import os
import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from booker.ack_repository import (
    ACCEPT,
    CANCEL_FAILED,
    CANCELLED,
    CONFIRMED,
    EXPIRED,
    FRIEND,
    OWNER,
    PENDING,
    AckRepository,
    invitee_id_for,
    iso,
    send_task_success,
    sfn_client,
    utcnow,
)
from booker.ack_roster import RosterEntry, load_roster
from booker.calendar_contract import utc_datetime
from booker.config import BookingsConfig, load_bookings
from booker.secrets import _client_kwargs

logger = logging.getLogger(__name__)

MIN_TIMEOUT_SECONDS = 60
SLOT_LEAD = timedelta(hours=6)
RETAIN_AFTER_SLOT = timedelta(days=7)
NOTIFY_KINDS = {"confirmed", "cancelled", "expired_notify_only", "cancel_failed"}


class MailError(RuntimeError):
    """SES rejected a message. Carries only the error code: SES text can include addresses."""


@lru_cache(maxsize=1)
def _ses_client():
    return boto3.client(
        "sesv2",
        config=Config(
            connect_timeout=2,
            read_timeout=5,
            retries={"mode": "standard", "total_max_attempts": 3},
        ),
        **_client_kwargs(),
    )


class Mailer:
    def __init__(self, client, sender: str) -> None:
        self.client = client
        self.sender = sender

    def send(self, to: str, subject: str, text: str, body_html: str) -> None:
        try:
            self.client.send_email(
                FromEmailAddress=self.sender,
                Destination={"ToAddresses": [to]},
                Content={
                    "Simple": {
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {
                            "Text": {"Data": text, "Charset": "UTF-8"},
                            "Html": {"Data": body_html, "Charset": "UTF-8"},
                        },
                    }
                },
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "Unknown")
            raise MailError(f"SES send_email failed: {code}") from None


def short_court(label: str) -> str:
    match = re.search(r"Court\s*\d+", label)
    return match.group(0) if match else label


def local_label(value: datetime, timezone: str, *, zone_name: bool = False) -> str:
    local = value.astimezone(ZoneInfo(timezone))
    text = f"{local:%a %b} {local.day} {local:%H:%M}"
    return f"{text} {local:%Z}" if zone_name else text


def _html_page(heading: str, lines: list[str], link: tuple[str, str] | None = None) -> str:
    """Minimal email HTML. Every interpolated value is escaped."""
    parts = [f"<h2>{html.escape(heading)}</h2>"]
    parts += [f"<p>{html.escape(line)}</p>" for line in lines]
    if link:
        url, label = link
        parts.append(
            f'<p><a href="{html.escape(url, quote=True)}" '
            'style="display:inline-block;padding:12px 18px;background:#1a73e8;'
            f'color:#fff;border-radius:6px;text-decoration:none">{html.escape(label)}</a></p>'
        )
    return '<!doctype html><html><body style="font-family:sans-serif">' + "".join(parts) + "</body></html>"


def _email(heading: str, lines: list[str], link: tuple[str, str] | None = None) -> tuple[str, str]:
    text = "\n\n".join([*lines, *([f"{link[1]}: {link[0]}"] if link else [])])
    return text + "\n", _html_page(heading, lines, link)


def invite_email(meta: dict, role: str, name: str, url: str) -> tuple[str, str, str]:
    slot, deadline = meta["slot_label"], meta["deadline_label"]
    required = int(meta["required"])
    if role == OWNER:
        subject = f"Court booked: {slot} - keep it?"
        lines = [
            f"The bot booked {slot}.",
            f"It needs {required} friends to accept by {deadline}, otherwise it is released.",
            "Open the link to keep it regardless of replies.",
        ]
        text, body = _email(subject, lines, (url, "Keep it anyway"))
    else:
        subject = f"Court booked: {slot} - are you in?"
        lines = [
            f"Hi {name}, a court is booked for {slot}.",
            f"The first {required} to accept play. Please answer by {deadline}.",
        ]
        text, body = _email(subject, lines, (url, "Answer"))
    return subject, text, body


def status_email(meta: dict, kind: str, accepted: list[str]) -> tuple[str, str, str]:
    slot = meta["slot_label"]
    if kind == "confirmed":
        subject = f"Court confirmed: {slot}"
        if meta.get("outcome") == "kept":
            lines = [f"{slot} is on. The owner kept the booking."]
        else:
            lines = [f"{slot} is on."]
        if accepted:
            lines.append("Playing: " + ", ".join(accepted))
    elif kind == "cancelled":
        subject = f"Court released: {slot}"
        lines = [f"Not enough friends accepted by {meta['deadline_label']}, so {slot} was cancelled."]
    elif kind == "expired_notify_only":
        subject = f"Court would have been released: {slot}"
        lines = [
            f"Not enough friends accepted by {meta['deadline_label']}.",
            f"Auto-cancel is in notify-only mode, so {slot} is still booked.",
        ]
    else:
        subject = f"Auto-cancel failed: {slot} - cancel manually"
        lines = [
            f"The acknowledgement window closed without quorum, but cancelling {slot} failed.",
            "Cancel it manually in Upace if you do not want it.",
        ]
    text, body = _email(subject, lines)
    return subject, text, body


def prepare(event: dict, *, repository: AckRepository, config: BookingsConfig, now=None) -> dict:
    booking = event["booking"]
    if booking.get("status") != "booked" or not booking.get("reservation_id"):
        raise ValueError("ack window needs a booked result with a reservation_id")
    reservation_id = str(booking["reservation_id"])
    activity = str(booking["activity"])
    now = utcnow(now).replace(microsecond=0)
    slot = utc_datetime(f"{booking['target_date']}T{booking['time']}", config.timezone)
    hours = int(event.get("ack_window_hours") or 24)
    deadline = min(now + timedelta(hours=hours), slot - SLOT_LEAD)
    deadline = max(deadline, now + timedelta(seconds=MIN_TIMEOUT_SECONDS))
    calendar = booking.get("calendar_reservation") or {}
    equipment_id = calendar.get("equipment_id") or config.equipment_id(activity)
    court = short_court(config.activity_label(activity))
    meta, created = repository.create_window(
        reservation_id,
        {
            "required": int(event.get("ack_required") or 2),
            "deadline": iso(deadline),
            "activity": activity,
            "date": str(booking["target_date"]),
            "time": str(booking["time"]),
            "equipment_id": int(equipment_id),
            "court": court,
            "slot_label": f"{local_label(slot, config.timezone)} ({court})",
            "deadline_label": local_label(deadline, config.timezone, zone_name=True),
            "booked_at": iso(now),
            "expires_at": int((max(slot, deadline) + RETAIN_AFTER_SLOT).timestamp()),
        },
    )
    stored_deadline = datetime.fromisoformat(meta["deadline"])
    timeout = max(MIN_TIMEOUT_SECONDS, math.ceil((stored_deadline - now).total_seconds()))
    logger.info("ack prepare reservation=%s created=%s timeout=%s", reservation_id, created, timeout)
    return {
        "reservation_id": reservation_id,
        "activity": meta["activity"],
        "date": meta["date"],
        "time": meta["time"],
        "timeout_seconds": timeout,
        "deadline": meta["deadline"],
    }


def send_invites(
    event: dict,
    *,
    repository: AckRepository,
    roster: dict[str, list[RosterEntry]],
    mailer: Mailer,
    sfn,
    owner_email: str,
    base_url: str,
    now=None,
) -> dict:
    reservation_id = str(event["reservation_id"])
    meta = repository.store_task_token(reservation_id, str(event["task_token"]))
    if meta["state"] != PENDING:
        # A retried wait task after an earlier confirmation: resume with the new token.
        if meta["state"] == CONFIRMED:
            send_task_success(sfn, meta["task_token"], meta.get("outcome", "confirmed"))
        return {}
    friends = [
        entry
        for entry in roster.get(meta["activity"], [])
        if entry.email.lower() != owner_email.strip().lower()
    ]
    if len(friends) < int(meta["required"]):
        logger.warning(
            "ack roster for %s has %d friends, fewer than required %s",
            meta["activity"], len(friends), meta["required"],
        )
    invitees = [(FRIEND, entry.name, entry.email) for entry in friends]
    if owner_email.strip():
        invitees.append((OWNER, "Owner", owner_email.strip()))
    sent = 0
    for role, name, email in invitees:
        token = repository.issue_invite(
            reservation_id, role=role, name=name, email=email, expires_at=int(meta["expires_at"])
        )
        if token is None:
            continue
        url = f"{base_url.rstrip('/')}/acks/{token}"
        mailer.send(email, *invite_email(meta, role, name, url))
        repository.mark_sent(reservation_id, invitee_id_for(role, email), now)
        sent += 1
    logger.info("ack invites reservation=%s sent=%d total=%d", reservation_id, sent, len(invitees))
    return {}


def expire(event: dict, *, repository: AckRepository, mode: str, now=None) -> dict:
    reservation_id = str(event["reservation_id"])
    meta = repository.expire(reservation_id, now)
    # A retried Expire sees its own earlier EXPIRED (or a later cancel outcome).
    expired = meta["state"] in (EXPIRED, CANCELLED, CANCEL_FAILED)
    cancel = expired and mode == "enforce"
    logger.info("ack expire reservation=%s state=%s cancel=%s", reservation_id, meta["state"], cancel)
    return {
        "expired": expired,
        "cancel": cancel,
        "cancel_event": {
            "source": "adhoc",
            "activity": meta["activity"],
            "date": meta["date"],
            "time": meta["time"],
            "cancel": True,
            "expected_reservation_id": reservation_id,
        },
    }


def notify(
    event: dict,
    *,
    repository: AckRepository,
    mailer: Mailer,
    owner_email: str,
    now=None,
) -> dict:
    reservation_id = str(event["reservation_id"])
    kind = str(event["kind"])
    if kind not in NOTIFY_KINDS:
        raise ValueError(f"unknown notify kind {kind!r}")
    if kind == "cancelled":
        repository.finish(reservation_id, CANCELLED, now)
    elif kind == "cancel_failed":
        repository.finish(reservation_id, CANCEL_FAILED, now)
    meta = repository.get_meta(reservation_id)
    if not meta:
        raise LookupError("unknown acknowledgement window")
    invitees = repository.list_invitees(reservation_id)
    accepted = [
        i["name"]
        for i in sorted(invitees, key=lambda i: i.get("responded_at", ""))
        if i.get("role") == FRIEND and i.get("response") == ACCEPT
    ]
    recipients: list[str] = []
    if kind != "cancel_failed":
        recipients = [i["email"] for i in invitees if i.get("sent_at")]
    if owner_email.strip():
        recipients.append(owner_email.strip())
    unique = list({email.lower(): email for email in recipients}.values())
    subject, text, body = status_email(meta, kind, accepted)
    for email in unique:
        mailer.send(email, subject, text, body)
    logger.info("ack notify reservation=%s kind=%s recipients=%d", reservation_id, kind, len(unique))
    return {}


def lambda_handler(event, context):  # noqa: ARG001
    action = event.get("action")
    repository = AckRepository()
    now = datetime.now(UTC)
    if action == "prepare":
        return prepare(event, repository=repository, config=load_bookings(), now=now)
    if action == "expire":
        return expire(event, repository=repository, mode=os.environ.get("ACK_MODE", "notify_only"), now=now)
    mailer = Mailer(_ses_client(), os.environ["ACK_SENDER_EMAIL"])
    owner_email = os.environ.get("OWNER_EMAIL", "")
    if action == "send_invites":
        return send_invites(
            event,
            repository=repository,
            roster=load_roster(),
            mailer=mailer,
            sfn=sfn_client(),
            owner_email=owner_email,
            base_url=os.environ["ACK_BASE_URL"],
            now=now,
        )
    if action == "notify":
        return notify(event, repository=repository, mailer=mailer, owner_email=owner_email, now=now)
    raise ValueError(f"unknown ack action {action!r}")
