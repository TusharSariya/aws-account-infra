from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from booker.schedule import (
    ScheduleError,
    format_people,
    format_ui_time,
    parse_hhmm,
    resolve_weekly_target,
    unlock_cron,
    unlock_weekday,
    warmup_cron,
)

TZ = ZoneInfo("America/St_Johns")


def test_format_ui_time_matches_upace_copy():
    assert format_ui_time(parse_hhmm("05:00")) == "5:00am"
    assert format_ui_time(parse_hhmm("18:00")) == "6:00pm"
    assert format_ui_time(parse_hhmm("12:00")) == "12:00pm"
    assert format_ui_time(parse_hhmm("00:00")) == "12:00am"
    assert format_people(1) == "1 person"
    assert format_people(2) == "2 people"


def test_unlock_weekday_is_three_calendar_days_earlier():
    assert unlock_weekday("Mon") == "Fri"
    assert unlock_weekday("Friday") == "Tue"


def test_unlock_cron_monday_1700_is_friday_1700():
    minute, hour, dow = unlock_cron("Mon", "17:00")
    assert (minute, hour, dow) == (0, 17, "FRI")


def test_warmup_cron_monday_1800_is_friday_1758():
    minute, hour, dow = warmup_cron("Mon", "18:00")
    assert (minute, hour, dow) == (58, 17, "FRI")


def test_warmup_cron_midnight_crosses_previous_day():
    minute, hour, dow = warmup_cron("Mon", "00:00")
    assert (minute, hour, dow) == (58, 23, "THU")


def test_friday_1758_resolves_monday_1800():
    now = datetime(2026, 8, 14, 17, 58, tzinfo=TZ)
    target = resolve_weekly_target(weekday="Mon", hhmm="18:00", now=now)
    assert target.late is False
    assert target.target_date.isoformat() == "2026-08-17"
    assert target.unlock_at == datetime(2026, 8, 14, 18, 0, tzinfo=TZ)
    assert target.warmup_at == datetime(2026, 8, 14, 17, 58, tzinfo=TZ)


def test_saturday_invoke_is_late():
    now = datetime(2026, 8, 15, 12, 0, tzinfo=TZ)
    target = resolve_weekly_target(weekday="Mon", hhmm="18:00", now=now)
    assert target.late is True


def test_bad_time_rejected():
    with pytest.raises(ScheduleError):
        parse_hhmm("6pm")
