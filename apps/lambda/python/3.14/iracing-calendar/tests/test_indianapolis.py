"""The newly published Indianapolis API identity must resolve to its special."""

from datetime import UTC, datetime

from test_api import HTML, SEASONS

from iracing_calendar.adapter import normalize
from iracing_calendar.catalog import load_catalog


def test_published_indianapolis_identity_has_five_timed_special_sessions():
    events, _, _ = normalize(
        SEASONS,
        load_catalog(2026),
        HTML,
        datetime(2026, 10, 9, tzinfo=UTC),
    )
    races = [
        event
        for event in events
        if event["provenance"].get("special_id") == "2026:8-hours-of-indianapolis"
    ]
    assert len(races) == 5
    assert {race["start"] for race in races} == {
        "2026-10-16T22:00:00+00:00",
        "2026-10-17T07:00:00+00:00",
        "2026-10-17T12:00:00+00:00",
        "2026-10-17T16:00:00+00:00",
        "2026-10-18T00:00:00+00:00",
    }
    assert all("special" in race["classification"] for race in races)
    assert all(not race["all_day"] for race in races)
    assert all(race["length"] == "480 minutes" for race in races)
    assert all(race["api_identity"]["track_id"] == 448 for race in races)
