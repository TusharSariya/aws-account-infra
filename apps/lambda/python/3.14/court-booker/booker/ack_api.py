"""Friend acknowledgement page. GET renders only; POST records one answer.

Link tokens are capabilities: they are never logged, and unknown or expired
tokens get the same generic 404.
"""

from __future__ import annotations

import base64
import binascii
import html
import logging
from datetime import UTC, datetime
from urllib.parse import parse_qs

from booker.ack_repository import (
    ACCEPT,
    CONFIRMED,
    DECLINE,
    OWNER,
    PENDING,
    AckRepository,
    Response,
    iso,
    send_task_success,
    sfn_client,
    utcnow,
)

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 1024
STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:32rem;margin:0 auto;padding:1.25rem;"
    "line-height:1.45;color:#1b1b1b;background:#fff}"
    "h1{font-size:1.4rem}.muted{color:#555}"
    "form{display:flex;gap:.75rem;flex-wrap:wrap;margin-top:1.25rem}"
    "button{flex:1 1 9rem;font-size:1.05rem;padding:.9rem 1rem;border-radius:.5rem;"
    "border:1px solid #888;background:#f3f3f3;color:#1b1b1b}"
    "button.yes{background:#1a73e8;border-color:#1a73e8;color:#fff}"
    "@media (prefers-color-scheme:dark){body{background:#121212;color:#eee}"
    ".muted{color:#aaa}button{background:#2a2a2a;color:#eee}}"
)


def _response(status: int, body: str) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
            ),
        },
        "body": body,
    }


def _page(title: str, paragraphs: list[str], form: tuple[str, str] | None = None) -> str:
    """Every interpolated value is escaped; no external assets."""
    parts = [f"<h1>{html.escape(title)}</h1>"]
    parts += [f"<p>{html.escape(p)}</p>" for p in paragraphs]
    if form:
        yes, no = form
        parts.append(
            '<form method="post">'
            f'<button class="yes" type="submit" name="response" value="{ACCEPT}">{html.escape(yes)}</button>'
            f'<button type="submit" name="response" value="{DECLINE}">{html.escape(no)}</button>'
            "</form>"
        )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f"<title>{html.escape(title)}</title><style>{STYLE}</style></head>"
        f"<body>{''.join(parts)}</body></html>"
    )


def _not_found() -> dict:
    return _response(404, _page("Link not found", ["This link is invalid or has expired."]))


def _answered_text(invitee: dict) -> str:
    return "You said you're in." if invitee.get("response") == ACCEPT else "You said you can't make it."


def render_status(meta: dict, invitee: dict, now: datetime, note: str = "") -> str:
    """The page for the current state. Shared by GET and the POST result."""
    slot = meta.get("slot_label", "")
    owner = invitee.get("role") == OWNER
    required = int(meta.get("required", 0))
    count = int(meta.get("ack_count", 0))
    details = [f"{slot}.", f"Answer by {meta.get('deadline_label', '')}."]
    lines = [note] if note else []
    if meta["state"] == CONFIRMED:
        if owner:
            return _page("Court confirmed", [*lines, f"{slot} is confirmed."])
        if invitee.get("response"):
            return _page("Court confirmed", [*lines, _answered_text(invitee), f"{slot} is on."])
        return _page("Court is full", [*lines, f"{required} friends already confirmed {slot}."])
    if invitee.get("response"):
        progress = f"{count} of {required} confirmed so far."
        return _page("Thanks", [*lines, _answered_text(invitee), f"{slot}.", progress])
    closed = meta["state"] != PENDING or (not owner and meta["deadline"] <= iso(now))
    if closed:
        return _page("Window closed", [*lines, f"The answer window for {slot} has closed."])
    if owner:
        return _page(
            "Keep this court?",
            [*lines, *details, f"{count} of {required} friends have accepted.",
             "Keep it confirms the booking now, whatever friends reply."],
            ("Keep it anyway", "Let friends decide"),
        )
    return _page(
        "Court booked - are you in?",
        [*lines, *details, f"The first {required} to accept play. {count} so far."],
        ("I'm in", "Can't make it"),
    )


NOTES = {
    "confirmed": "You're in, and that completes the court.",
    "kept": "Kept. The booking is confirmed.",
    "accepted": "You're in.",
    "declined": "Thanks for letting us know.",
    "already_answered": "You already answered.",
    "full": "Sorry, the court filled before your answer.",
    "closed": "Sorry, the answer window closed before your answer.",
}


def _form_response(event: dict) -> str | None:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(body, validate=True)
        except (binascii.Error, ValueError):
            return None
    else:
        raw = body.encode() if isinstance(body, str) else b""
    if len(raw) > MAX_BODY_BYTES:
        return None
    try:
        values = parse_qs(raw.decode("utf-8"), max_num_fields=5).get("response", [])
    except (UnicodeDecodeError, ValueError):
        return None
    return values[0] if len(values) == 1 and values[0] in (ACCEPT, DECLINE) else None


def _callback(sfn, result: Response) -> None:
    try:
        send_task_success(sfn, result.meta.get("task_token"), result.outcome)
    except Exception:  # noqa: BLE001 - state is committed; Expire re-reads it
        # No exception text: SDK errors can echo the task token.
        logger.error("ack callback failed; expire step will reconcile")


def serve(event: dict, repository, sfn, now: datetime | None = None) -> dict:
    now = utcnow(now)
    method = ((event.get("requestContext") or {}).get("http") or {}).get("method", "GET")
    token = (event.get("pathParameters") or {}).get("token", "")
    resolved = repository.resolve_token(token, now)
    if resolved is None:
        return _not_found()
    meta, invitee = resolved
    if method == "GET":
        return _response(200, render_status(meta, invitee, now))
    if method != "POST":
        return _response(405, _page("Not allowed", ["Use the buttons on the page."]))
    answer = _form_response(event)
    if answer is None:
        return _response(400, _page("Bad request", ["Choose one of the buttons."]))
    if invitee.get("role") == OWNER and answer == DECLINE:
        # "Let friends decide" changes nothing, so the owner can still keep it later.
        return _response(200, render_status(meta, invitee, now, "Friends decide, then."))
    result = repository.respond(meta["reservation_id"], invitee["invitee_id"], answer, now)
    logger.info("ack answer reservation=%s outcome=%s", meta["reservation_id"], result.outcome)
    if result.outcome in ("confirmed", "kept"):
        _callback(sfn, result)
    return _response(200, render_status(result.meta, result.invitee, now, NOTES[result.outcome]))


def lambda_handler(event, context):  # noqa: ARG001
    return serve(event, AckRepository(), _LazySfn(), datetime.now(UTC))


class _LazySfn:
    """Create the Step Functions client only when an answer completes the window."""

    def send_task_success(self, **kwargs):
        return sfn_client().send_task_success(**kwargs)
