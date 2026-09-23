"""Deterministic shared-calendar serialization."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from icalendar import Calendar, Event


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Calendar timestamps must include a timezone")
    return parsed.astimezone(UTC)


def render_calendar(reservations: list[dict]) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", "-//Court Booker//Shared Reservations//EN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("x-wr-calname", "Court bookings")
    for reservation in sorted(
        reservations, key=lambda item: str(item["reservation_id"])
    ):
        if reservation["status"] != "confirmed":
            continue
        event = Event()
        # Hash opaque upstream IDs to keep UID syntax safe and identity stable.
        identity = hashlib.sha256(
            str(reservation["reservation_id"]).encode()
        ).hexdigest()
        event.add("uid", f"{identity}@court-booker")
        event.add("dtstart", _utc(reservation["start"]))
        event.add("dtend", _utc(reservation["end"]))
        event.add("dtstamp", _utc(reservation["updated_at"]))
        event.add("last-modified", _utc(reservation["updated_at"]))
        event.add(
            "created", _utc(reservation.get("created_at", reservation["updated_at"]))
        )
        event.add("sequence", int(reservation["sequence"]))
        event.add("summary", reservation["court"])
        event.add("location", reservation["location"])
        event.add("status", "CONFIRMED")
        calendar.add_component(event)
    return calendar.to_ical()
