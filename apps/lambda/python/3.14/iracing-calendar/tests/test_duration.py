import copy
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import vobject
from test_api import HTML, NOW, SEASONS

from iracing_calendar.adapter import normalize, session_blocks
from iracing_calendar.announcements import supplement
from iracing_calendar.api import ContractError
from iracing_calendar.catalog import load_catalog
from iracing_calendar.duration import end_time, race_duration
from iracing_calendar.migration import differences
from iracing_calendar.reconcile import reconcile
from iracing_calendar.sources import NEWS


def test_captured_session_blocks_render_timed_lap_and_capped_races():
    events, coverage, _ = normalize(SEASONS, load_catalog(2026), HTML, NOW)
    # Race minutes alone omit attached practice/qualifying and session overhead.
    for season_id, minutes, kind in [
        (6465, 134, "session_estimate"),
        (6623, 641, "session_estimate"),
        (6624, 399, "session_estimate"),
        (6262, 1481, "session_time_cap"),
        (6072, 1481, "session_estimate"),
    ]:
        race = next(
            e for e in events if e.get("api_identity", {}).get("season_id") == season_id
        )
        assert datetime.fromisoformat(race["end"]) - datetime.fromisoformat(
            race["start"]
        ) == timedelta(minutes=minutes)
        assert race["duration"]["kind"] == kind
        result = reconcile({}, [race], coverage, datetime.fromisoformat(race["start"]))
        parsed = vobject.readOne(result["ics"]).vevent
        assert parsed.dtend.value - parsed.dtstart.value == timedelta(minutes=minutes)
        if kind == "session_time_cap":
            assert "not an expected finish" in parsed.description.value
        else:
            assert "End time is estimated" in parsed.description.value
    placeholders = [e for e in events if e["all_day"]]
    assert placeholders and all(
        len(e["start"]) == len(e["end"]) == 10 for e in placeholders
    )


def test_descriptor_durations_follow_their_own_starts_and_recurrences():
    round_ = copy.deepcopy(SEASONS[0]["schedules"][0])
    first, second = round_["race_time_descriptors"][0]["session_times"]
    round_["race_time_descriptors"] = [
        {"repeating": False, "session_minutes": 751, "session_times": [first]},
        {"repeating": False, "session_minutes": 781, "session_times": [second]},
    ]
    blocks = session_blocks(round_)
    assert [blocks[datetime.fromisoformat(t)]["minutes"] for t in (first, second)] == [
        751,
        781,
    ]
    round_["race_time_descriptors"][1]["session_times"] = [first]
    with pytest.raises(ContractError, match="Conflicting durations"):
        session_blocks(round_)
    recurring = next(s for s in SEASONS if s["season_id"] == 6508)["schedules"][0]
    assert session_blocks(recurring) == {}
    blocks = session_blocks(recurring, include_repeating=True)
    assert len(blocks) > 1 and all(d["minutes"] == 79 for d in blocks.values())


@pytest.mark.parametrize("value", [0, -1, True, "134", 134.5])
def test_invalid_published_duration_blocks_publication(value):
    with pytest.raises(ContractError, match="duration"):
        race_duration({"race_time_limit": 120}, {"session_minutes": value})


def test_time_limit_fallback_does_not_invent_lap_times_or_double_count_overhead():
    assert race_duration({"race_time_limit": 120}) == {
        "minutes": 120,
        "source": "race_time_limit",
        "kind": "race_time_limit",
    }
    assert race_duration({"race_lap_limit": 100, "race_time_limit": None}) is None
    assert end_time("2026-10-03T12:00:00+00:00", None) is None
    with pytest.raises(ContractError, match="shorter"):
        race_duration({"race_time_limit": 120}, {"session_minutes": 119})


def test_duration_change_keeps_uid_increments_sequence_and_changes_etag_once():
    events, coverage, _ = normalize(SEASONS, load_catalog(2026), HTML, NOW)
    race = next(e for e in events if e.get("api_identity", {}).get("season_id") == 6624)
    legacy = {k: v for k, v in race.items() if k != "duration"} | {"end": None}
    before = reconcile({}, [legacy], coverage, NOW)
    after = reconcile(before, [race], coverage, NOW + timedelta(hours=6))
    old, new = (vobject.readOne(s["ics"]).vevent for s in (before, after))
    assert old.uid.value == new.uid.value
    assert int(new.sequence.value) == int(old.sequence.value) + 1
    assert before["etag"] != after["etag"]
    diff = differences(before, after)
    assert not diff["start_changes"] and len(diff["end_changes"]) == 1
    assert diff["end_changes"][0]["before"] is None
    assert diff["end_changes"][0]["after"] == race["end"]
    same = reconcile(after, [race], coverage, NOW + timedelta(hours=12))
    assert same["ics"] == after["ics"] and same["etag"] == after["etag"]


def test_session_block_crosses_midnight_and_newfoundland_dst():
    start = "2026-11-01T02:00:00+00:00"
    end = end_time(start, {"minutes": 399})
    local = ZoneInfo("America/St_Johns")
    assert (
        datetime.fromisoformat(start).astimezone(local).isoformat()
        == "2026-10-31T23:30:00-02:30"
    )
    assert (
        datetime.fromisoformat(end).astimezone(local).isoformat()
        == "2026-11-01T05:09:00-03:30"
    )
    assert datetime.fromisoformat(end) - datetime.fromisoformat(start) == timedelta(
        minutes=399
    )


def test_announcement_confirmation_turns_dated_timed_special_into_duration_block():
    catalog = load_catalog(2026)
    entry = next(e for e in catalog["events"] if e["name"] == "8 Hours of Indianapolis")
    # Exercise the pre-publication announcement fallback independently of the
    # subsequently reviewed API mapping and captured Indianapolis schedule.
    entry["api_mappings"] = []
    seasons = [season for season in SEASONS if season["season_id"] != 6626]
    events, coverage, _ = normalize(seasons, catalog, HTML, NOW)
    placeholder = next(
        e for e in events if e.get("provenance", {}).get("special_id") == entry["id"]
    )
    before = reconcile({}, [placeholder], coverage, NOW)
    url = "https://www.iracing.com/this-week-iracing-special-event/"

    class Fetch:
        def __init__(self):
            self.cache = {}

        def get(self, address):
            if address == NEWS:
                return f'<a href="{url}">Event</a>'
            return '<div class="page-header"><h1>8 Hours of Indianapolis</h1></div><p>ABOUT THE 2026 EVENT</p><ul><li>Timeslot #1: Saturday at 12:00 GMT</li></ul>'

    supplement(events, catalog, Fetch(), NOW)
    race = next(
        e for e in events if e.get("provenance", {}).get("special_id") == entry["id"]
    )
    assert race["start"] == "2026-10-17T12:00:00+00:00"
    assert race["end"] == "2026-10-17T20:00:00+00:00"
    after = reconcile(before, [race], coverage, NOW)
    old, new = (vobject.readOne(s["ics"]).vevent for s in (before, after))
    assert old.uid.value == new.uid.value
    assert "not included" in new.description.value
    assert new.dtend.value == datetime(2026, 10, 17, 20, tzinfo=UTC)
