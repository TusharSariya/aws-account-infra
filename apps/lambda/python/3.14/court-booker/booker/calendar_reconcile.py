"""Read-only Upace reconciliation with complete validation before persistence."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from booker.calendar_contract import normalize_reservation, utc_datetime
from booker.calendar_repository import CalendarRepository, utcnow
from booker.config import load_bookings
from booker.http import GeneratedUpaceSession
from booker.secrets import load_credentials


class CalendarRefreshFailed(RuntimeError):
    pass


def reconcile(repository, session, config, credentials, lease_id, *, now=None):
    current = utcnow(now)
    repository.assert_lease(lease_id, now)
    snapshot = repository.snapshot()
    start = current.astimezone(ZoneInfo(config.timezone)).date()
    end = start + timedelta(days=180)
    session.login(credentials.username, credentials.password)
    rows = session.reservations(start, end)
    if not isinstance(rows, list):
        raise TypeError("reservation response is not complete")
    labels = {
        value: config.activity_label(key) for key, value in config.equipment_ids.items()
    }
    activities = {value: key for key, value in config.equipment_ids.items()}
    zone = ZoneInfo(config.timezone)
    reservations = {}
    for row in rows:
        equipment_id = (
            row.equipment_id if row.equipment_id is not None else row.class_id
        )
        if equipment_id not in labels:
            continue
        normalized = normalize_reservation(
            reservation_id=str(row.id),
            equipment_id=equipment_id,
            start=row.start_time,
            end=row.end_time,
            court=labels[equipment_id],
            timezone=config.timezone,
            status="cancelled" if row.cancelled else "confirmed",
        )
        local_start = utc_datetime(normalized["start"]).astimezone(zone)
        when = local_start.date()
        if not start <= when < end:
            continue
        # Rows matching a private weekly rule (enabled or not) are private. The
        # repository keeps an existing private record private regardless.
        visibility, title = config.visibility_for(
            activities[equipment_id], local_start.replace(tzinfo=None)
        )
        normalized["visibility"] = visibility
        if title:
            normalized["title"] = title
        if normalized["reservation_id"] in reservations:
            raise ValueError("duplicate reservation in upstream response")
        reservations[normalized["reservation_id"]] = normalized
    # Build the full mutation set before the first write. Missing records only
    # cancel inside the exact queried time/equipment window.
    for reservation_id, old in snapshot.items():
        when = utc_datetime(old["start"]).astimezone(ZoneInfo(config.timezone)).date()
        if (
            reservation_id not in reservations
            and old["equipment_id"] in labels
            and start <= when < end
            and old["status"] == "confirmed"
        ):
            reservations[reservation_id] = {
                k: old[k]
                for k in (
                    "reservation_id",
                    "equipment_id",
                    "start",
                    "end",
                    "court",
                    "location",
                    "status",
                    "visibility",
                    "title",
                )
                if k in old
            }
            reservations[reservation_id]["status"] = "cancelled"
    changed = 0
    for reservation_id, reservation in reservations.items():
        changed += repository.put_reservation(
            reservation,
            expected_version=snapshot.get(reservation_id, {}).get("version"),
            lease_id=lease_id,
            now=now,
        )
    repository.finish_refresh(lease_id, now)
    return {"status": "synced", "changed": changed, "reservations": len(rows)}


def lambda_handler(event, context):
    repository = CalendarRepository()
    lease_id = (event or {}).get("lease_id")
    if lease_id is None:
        lease_id = repository.claim_refresh(force=True)
        if lease_id is None:
            return {"status": "busy"}
    elif repository.get_metadata().get("lease_id") != lease_id:
        # An async retry can arrive after the failed attempt released its lease.
        lease_id = repository.claim_refresh()
        if lease_id is None:
            return {"status": "busy"}
    try:
        return reconcile(
            repository,
            GeneratedUpaceSession(),
            load_bookings(),
            load_credentials(),
            lease_id,
        )
    except Exception:  # noqa: BLE001 - sanitize all upstream errors at the Lambda boundary
        repository.release_refresh(lease_id)
        # Exception messages/payloads from upstream can contain personal details.
        # Emit only a fixed failure; Lambda Errors and its async destination alert.
        raise CalendarRefreshFailed(
            "calendar reconciliation failed; last successful refresh unchanged"
        ) from None
