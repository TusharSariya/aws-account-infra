from datetime import UTC, datetime

from icalendar import Calendar
from test_turnout import ROW

from zwift_calendar.calendar import split_calendars
from zwift_calendar.duration_filter import apply


def test_upper_bound_not_central_duration_and_exact_boundary():
    rows = [
        ROW | {"duration": {"seconds": 6000, "upper_seconds": upper}}
        for upper in (8999, 9000, 9001)
    ]
    kept, report = apply(rows)
    assert kept == rows[:2]
    assert report["filtered"] == 1
    assert report["filtered_by_calendar"] == {"banded": 1, "unbanded": 0}


def test_published_unknown_special_rides_and_both_feeds():
    rows = [
        ROW | {"band": band, "duration": {"seconds": seconds}}
        for band in (None, "0-180")
        for seconds in (9000, 9001, None)
    ]
    special = ROW | {"event_kind": "special_ride", "duration": {"seconds": 20000}}
    kept, report = apply([*rows, special])
    assert len(kept) == 5
    assert special in kept
    assert report["filtered_by_calendar"] == {"banded": 1, "unbanded": 1}
    assert report["unknown_races_retained"] == 2


def test_filtered_race_disappears_and_returns_with_stable_uid():
    now = datetime(2026, 10, 11, 12, tzinfo=UTC)
    first, revisions = split_calendars([ROW], {}, now)
    original = Calendar.from_ical(first["calendars"]["banded"]["ics"]).walk("VEVENT")[0]
    long = ROW | {"duration": ROW["duration"] | {"upper_seconds": 9001}}
    kept, _ = apply([long])
    hidden, revisions = split_calendars(kept, revisions, now)
    assert not Calendar.from_ical(hidden["calendars"]["banded"]["ics"]).walk("VEVENT")
    restored, _ = split_calendars([ROW], revisions, now)
    event = Calendar.from_ical(restored["calendars"]["banded"]["ics"]).walk("VEVENT")[0]
    assert event["UID"] == original["UID"]
    assert event["SEQUENCE"] == original["SEQUENCE"]
