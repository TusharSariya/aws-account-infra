import copy
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pytest
from icalendar import Calendar

from zwift_calendar.api import Zwift
from zwift_calendar.calendar import split_calendars
from zwift_calendar.errors import ContractError, UpstreamError
from zwift_calendar.turnout import apply, evidence, populate

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
ROW = {
    "id": "3-30",
    "event_id": 3,
    "subgroup_id": 30,
    "parent_id": 2,
    "start": NOW.isoformat(),
    "turnout_division": ["score", "0-180"],
    "signature": [1, 10000, 0, "RACE"],
    "band": "0-180",
    "group": "E",
    "name": "Test race",
    "url": "https://www.zwift.com/events/view/3",
    "duration": {"seconds": 2400, "source": "published", "samples": 0},
    "time_trial": False,
    "provisional": False,
    "requirements": [],
}


def cache(counts):
    return {
        str(2 - i): {
            "parent": 1 - i,
            "start": (NOW - timedelta(weeks=i + 1)).isoformat(),
            "type": "RACE",
            "groups": [
                {
                    "id": (2 - i) * 10,
                    "division": ROW["turnout_division"],
                    "start": (NOW - timedelta(weeks=i + 1)).isoformat(),
                    "finishers": n,
                }
            ],
        }
        for i, n in enumerate(counts)
    }


def test_average_threshold_and_unknown_are_distinct():
    for counts, expected, mean in [
        ([8, 10], 0, 9),
        ([9, 11], 1, 10),
        ([0, 0], 0, 0),
        ([50], 1, None),
        ([], 1, None),
    ]:
        rows, report = apply(
            [copy.deepcopy(ROW)], {"turnout_events": cache(counts)}, NOW
        )
        assert len(rows) == expected
        assert report["filtered"] == 1 - expected
        assert report["unknown"] == int(mean is None)
        if rows:
            assert rows[0]["turnout"]["average"] == mean


def test_other_divisions_and_time_slots_do_not_supply_popularity():
    for mutate in ["division", "time", "type"]:
        data = cache([30, 40])
        if mutate == "division":
            data["2"]["groups"][0]["division"] = ["score", "180-350"]
        if mutate == "time":
            data["2"]["groups"][0]["start"] = (
                NOW - timedelta(weeks=1, hours=1)
            ).isoformat()
        if mutate == "type":
            data["2"]["type"] = "TIME_TRIAL"
        rows, report = apply([copy.deepcopy(ROW)], {"turnout_events": data}, NOW)
        assert report["unknown"] == 1 and rows[0]["turnout"]["average"] is None


def test_average_is_in_ics_and_revisions_stay_stable():
    rows, _ = apply([copy.deepcopy(ROW)], {"turnout_events": cache([18, 23])}, NOW)
    first, revisions = split_calendars(rows, {}, NOW)
    parsed = Calendar.from_ical(first["calendars"]["banded"]["ics"]).walk("VEVENT")[0]
    assert (
        "Expected finishers in your division: 20.5 (historical average across 2"
        in str(parsed["DESCRIPTION"])
    )
    assert str(parsed["X-ZWIFT-AVERAGE-FINISHERS"]) == "20.5"
    again, _ = split_calendars(rows, revisions, NOW + timedelta(hours=1))
    assert again["calendars"] == first["calendars"]


def result(i, group=10):
    return {
        "profileId": i,
        "eventSubgroupId": group,
        "qualified": True,
        "rank": i + 1,
        "activityData": {"durationInMilliseconds": 100000},
    }


def test_complete_results_paginate_to_empty_and_ignore_disqualified():
    api = Zwift(Mock(), "token")
    rows = [result(i) for i in range(35)]
    rows[0]["qualified"] = False
    calls = []

    def get(path, **kwargs):
        query = parse_qs(urlparse(path).query)
        start = int(query["start"][0])
        calls.append(start)
        return {"entries": rows[start : start + 25]}

    api.get = get
    assert api.finisher_count(10) == 34
    assert calls == [0, 25, 50]


@pytest.mark.parametrize("failure", ["overlap", "wrong_group", "partial", "malformed"])
def test_incomplete_results_never_become_a_count(failure):
    api = Zwift(Mock(), "token")
    first = {"entries": [result(i) for i in range(25)]}
    second = (
        {"entries": [result(0)]}
        if failure == "overlap"
        else {"entries": [result(26, 11)]}
        if failure == "wrong_group"
        else UpstreamError("failed")
        if failure == "partial"
        else {}
    )
    api.get = Mock(side_effect=[first, second])
    with pytest.raises((ContractError, UpstreamError)):
        api.finisher_count(10)


def test_collection_resumes_and_stores_no_rider_records():
    state = {"turnout_events": cache([15, 20])}
    del state["turnout_events"]["2"]["groups"][0]["finishers"]
    api = Mock()
    api.http.remaining = 120
    api.http.clock.return_value = 0
    api.http.deadline = 150

    def count(group):
        api.http.remaining -= 2
        return 18

    api.finisher_count.side_effect = count
    populate(api, state, {"turnout": [ROW]}, NOW)
    assert evidence(ROW, state["turnout_events"], NOW)[1] is None
    assert state["turnout_events"]["2"]["groups"][0]["finishers"] == 18
    populate(api, state, {"turnout": [ROW]}, NOW)
    assert api.finisher_count.call_count == 1


def test_special_rides_are_not_filtered():
    rows, report = apply(
        [ROW | {"event_kind": "special_ride"}], {"turnout_events": cache([0, 0])}, NOW
    )
    assert len(rows) == 1 and report["filtered"] == 0


def test_collection_filters_and_reports_but_keeps_backfill_targets():
    import json
    from pathlib import Path

    from zwift_calendar.api import instant
    from zwift_calendar.service import collect

    race = json.loads((Path(__file__).parent / "fixtures/race.json").read_text())
    race["parentId"] = 2
    race["name"] = "Synthetic eligible race"
    now = instant(race["eventStart"]) - timedelta(minutes=1)
    api = Mock()
    api.profile.return_value = {
        "current": 100,
        "max30": 100,
        "retrieved_at": now.timestamp(),
        "fields": {"profile.playerType": "NORMAL", "profile.male": True},
    }
    api.upcoming.return_value = [race]
    _, initial, _ = collect(api, {}, now)
    row = next(iter(initial["revisions"].values()))
    data = cache([8, 9])
    for i in (1, 2):
        start = (instant(row["start"]) - timedelta(weeks=3 - i)).isoformat()
        data[str(i)]["start"] = start
        data[str(i)]["groups"][0].update(start=start, division=row["turnout_division"])
    snapshot, state, report = collect(api, {"history": {"turnout_events": data}}, now)
    assert report["before_turnout_filter"] == 1
    assert report["matched"] == 0 and report["turnout"]["filtered_banded"] == 1
    assert state["_targets"]["turnout"][0]["parent_id"] == 2
    assert all(
        not Calendar.from_ical(f["ics"]).walk("VEVENT")
        for f in snapshot["calendars"].values()
    )


def test_unknown_reasons_distinguish_pending_from_missing_history():
    _, pending = apply([copy.deepcopy(ROW)], {}, NOW)
    _, no_parent = apply([ROW | {"parent_id": None}], {}, NOW)
    _, insufficient = apply(
        [copy.deepcopy(ROW)],
        {
            "turnout_events": cache([20])
            | {
                "1": {
                    "parent": None,
                    "start": (NOW - timedelta(weeks=2)).isoformat(),
                    "type": "RACE",
                    "groups": [],
                }
            }
        },
        NOW,
    )
    assert pending["pending_history"] == 1
    assert no_parent["no_parent_link"] == 1
    assert insufficient["insufficient_history"] == 1


def test_missing_finisher_status_is_not_a_zero_count():
    api = Zwift(Mock(), "token")
    api.get = Mock(return_value={"entries": [{"profileId": 1, "eventSubgroupId": 10}]})
    with pytest.raises(ContractError):
        api.finisher_count(10)


def test_collection_prioritizes_unknown_races_before_six_edition_depth():
    data = cache([18, 20])
    data["1"]["parent"] = 5
    api = Mock()
    api.http.remaining = 120
    api.http.clock.return_value = 0
    api.http.deadline = 150

    def fetch(identity):
        api.http.remaining -= 1
        return {
            "parentId": None,
            "eventStart": (NOW - timedelta(days=7)).isoformat(),
            "eventType": "RACE",
            "eventSubgroups": [],
        }

    api.event.side_effect = fetch
    other = ROW | {
        "id": "4-40",
        "parent_id": 10,
        "start": (NOW + timedelta(days=1)).isoformat(),
    }
    populate(api, {"turnout_events": data}, {"turnout": [ROW, other]}, NOW, budget=1)
    api.event.assert_called_once_with(10)


def test_duration_results_include_riders_beyond_first_page():
    api = Zwift(Mock(), "token")

    def result(identity):
        return {
            "profileId": identity,
            "eventSubgroupId": 10,
            "qualified": True,
            "rank": identity,
            "activityData": {"durationInMilliseconds": 2400000},
        }

    api.get = Mock(
        side_effect=[
            {"entries": [result(i) for i in range(1, 26)]},
            {"entries": [result(26)]},
            {"entries": []},
        ]
    )
    rows = api.results(10)
    assert len(rows) == 26
    assert "start=25" in api.get.call_args_list[1].args[0]
    assert "start=50" in api.get.call_args_list[2].args[0]
