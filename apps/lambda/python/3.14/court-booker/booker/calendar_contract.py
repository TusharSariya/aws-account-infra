"""Shared, validated calendar boundary. All persisted event times are UTC."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

VISIBILITIES = ("public", "private")


def utc_datetime(value: str | datetime, timezone: str = "America/St_Johns") -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(parsed, datetime):
        raise TypeError("reservation timestamp must be a datetime")
    if parsed.tzinfo is None:
        zone = ZoneInfo(timezone)
        early = parsed.replace(tzinfo=zone, fold=0)
        late = parsed.replace(tzinfo=zone, fold=1)
        if early.utcoffset() != late.utcoffset():
            raise ValueError(
                "ambiguous or nonexistent local reservation time requires an offset"
            )
        parsed = early
    return parsed.astimezone(UTC)


def normalize_reservation(
    *,
    reservation_id: str | int,
    equipment_id: int,
    start: str | datetime,
    end: str | datetime,
    court: str,
    location: str = "Ches Penney Family YMCA",
    status: str = "confirmed",
    timezone: str = "America/St_Johns",
    visibility: str = "public",
    title: str | None = None,
) -> dict:
    if (
        isinstance(reservation_id, bool)
        or not str(reservation_id).strip()
        or reservation_id is None
    ):
        raise ValueError("reservation id is required")
    if isinstance(equipment_id, bool) or int(equipment_id) <= 0:
        raise ValueError("equipment id must be positive")
    if status not in {"confirmed", "cancelled"}:
        raise ValueError("invalid reservation status")
    if not isinstance(court, str) or not court.strip():
        raise ValueError("court name is required")
    if not isinstance(location, str) or not location.strip():
        raise ValueError("location is required")
    if visibility not in VISIBILITIES:
        raise ValueError("invalid reservation visibility")
    if title is not None and not isinstance(title, str):
        raise ValueError("reservation title must be text")
    first, last = utc_datetime(start, timezone), utc_datetime(end, timezone)
    if last <= first:
        raise ValueError("reservation end must follow its start")
    reservation = {
        "reservation_id": str(reservation_id),
        "equipment_id": int(equipment_id),
        "start": first.isoformat(),
        "end": last.isoformat(),
        "court": court,
        "location": location,
        "status": status,
        "visibility": visibility,
    }
    # DynamoDB items never carry a None title; absent means untitled.
    if title and title.strip():
        reservation["title"] = title.strip()
    return reservation
