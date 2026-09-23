"""Publish a completed reservation operation without ever repeating it."""

from booker.calendar_contract import normalize_reservation
from booker.calendar_repository import CalendarRepository


def lambda_handler(event, context):
    if event.get("dry_run") or event.get("status") not in {
        "booked",
        "already_held",
        "cancelled",
    }:
        return {"status": "skipped"}
    raw = event.get("calendar_reservation")
    if not isinstance(raw, dict):
        raise TypeError("successful reservation missing calendar metadata")
    reservation = normalize_reservation(**raw)
    expected_status = "cancelled" if event["status"] == "cancelled" else "confirmed"
    if reservation["status"] != expected_status:
        raise ValueError("reservation status contradicts booking result")
    CalendarRepository().put_reservation(reservation)
    return {"status": "published", "reservation_id": reservation["reservation_id"]}
