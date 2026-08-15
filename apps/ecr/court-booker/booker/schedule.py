from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
AWS_DOW = {
    "Mon": "MON",
    "Tue": "TUE",
    "Wed": "WED",
    "Thu": "THU",
    "Fri": "FRI",
    "Sat": "SAT",
    "Sun": "SUN",
}
# Slot weekday -> unlock weekday (exactly 72 hours / 3 calendar days earlier).
UNLOCK_WEEKDAY = {
    "Mon": "Fri",
    "Tue": "Sat",
    "Wed": "Sun",
    "Thu": "Mon",
    "Fri": "Tue",
    "Sat": "Wed",
    "Sun": "Thu",
}


class ScheduleError(ValueError):
    """Invalid weekday, clock time, or late weekly invoke."""


@dataclass(frozen=True)
class WeeklyTarget:
    target_date: date
    slot_time: time
    unlock_at: datetime
    warmup_at: datetime
    weekday: str
    late: bool = False


def parse_hhmm(value: str) -> time:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ScheduleError(f"time must be HH:MM, got {value!r}")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ScheduleError(f"time must be HH:MM, got {value!r}") from exc
    if hour not in range(24) or minute not in range(60):
        raise ScheduleError(f"time out of range: {value!r}")
    return time(hour, minute)


def format_ui_time(slot: time) -> str:
    """Upace copy uses '5:00am' / '6:00pm', no leading zero on the hour."""
    hour = slot.hour % 12 or 12
    suffix = "am" if slot.hour < 12 else "pm"
    return f"{hour}:{slot.minute:02d}{suffix}"


def format_duration(duration_min: int) -> str:
    return f"{duration_min} mins"


def format_people(people: int) -> str:
    noun = "person" if people == 1 else "people"
    return f"{people} {noun}"


def normalize_weekday(value: str) -> str:
    key = value.strip()[:3].title()
    if key not in WEEKDAYS:
        raise ScheduleError(f"unknown weekday: {value!r}")
    return key


def unlock_weekday(weekday: str) -> str:
    return UNLOCK_WEEKDAY[normalize_weekday(weekday)]


def slot_unlock_at(target_date: date, slot: time, horizon_hours: int = 72) -> datetime:
    """EventBridge fire time: the court slot minus the booking horizon."""
    return datetime.combine(target_date, slot) - timedelta(hours=horizon_hours)


def unlock_cron(weekday: str, hhmm: str) -> tuple[int, int, str]:
    """EventBridge cron fields for the unlock instant: minute, hour, AWS day-of-week.

    Retries live in Step Functions (60s apart), not as a warmup offset here.
    """
    slot = parse_hhmm(hhmm)
    return slot.minute, slot.hour, AWS_DOW[unlock_weekday(weekday)]


def warmup_cron(weekday: str, hhmm: str, warmup_minutes: int = 2) -> tuple[int, int, str]:
    """Legacy T-warmup cron fields. Prefer unlock_cron; Lambda no longer sleeps."""
    slot = parse_hhmm(hhmm)
    unlock_dow = AWS_DOW[unlock_weekday(weekday)]
    total = slot.hour * 60 + slot.minute - warmup_minutes
    prev = {
        "MON": "SUN",
        "TUE": "MON",
        "WED": "TUE",
        "THU": "WED",
        "FRI": "THU",
        "SAT": "FRI",
        "SUN": "SAT",
    }
    if total < 0:
        total += 24 * 60
        unlock_dow = prev[unlock_dow]
    return total % 60, total // 60, unlock_dow


def resolve_weekly_target(
    *,
    weekday: str,
    hhmm: str,
    now: datetime,
    horizon_hours: int = 72,
    require_unlock_day: bool = True,
    warmup_minutes: int = 2,
) -> WeeklyTarget:
    """Map a weekly rule onto the slot that opens `horizon_hours` from `now`.

    Cron fires on the unlock day (slot weekday minus 3 days) at the same
    clock time. Step Functions retries the Lambda three times, 60s apart.
    A late invoke (wrong local day) is marked `late=True` rather than
    booking a different date.
    """
    weekday = normalize_weekday(weekday)
    slot = parse_hhmm(hhmm)
    tz = now.tzinfo or ZoneInfo("America/St_Johns")
    now = now.astimezone(tz)
    expected_unlock = unlock_weekday(weekday)
    today = now.strftime("%a")
    late = require_unlock_day and today != expected_unlock
    horizon_days = horizon_hours // 24
    target_date = now.date() + timedelta(days=horizon_days)
    if WEEKDAYS[target_date.weekday()] != weekday and not late:
        raise ScheduleError(
            f"unlock day {today} + {horizon_days}d is {target_date} "
            f"({WEEKDAYS[target_date.weekday()]}), expected {weekday}"
        )
    unlock_at = datetime.combine(now.date(), slot, tzinfo=tz)
    warmup_at = unlock_at - timedelta(minutes=warmup_minutes)
    return WeeklyTarget(
        target_date=target_date,
        slot_time=slot,
        unlock_at=unlock_at,
        warmup_at=warmup_at,
        weekday=weekday,
        late=late,
    )
