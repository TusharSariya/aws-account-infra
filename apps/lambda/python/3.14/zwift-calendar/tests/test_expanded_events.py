import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import vobject

from zwift_calendar.api import instant
from zwift_calendar.calendar import reconcile
from zwift_calendar.campaigns import campaign
from zwift_calendar.duration import estimate, learn
from zwift_calendar.filtering import select
from zwift_calendar.service import weekly_counts

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE = {
    "current": 100,
    "max30": 100,
    "fields": {
        "profile.playerType": "NORMAL",
        "profile.profileId": 1,
        "profile.male": True,
        "profile.age": 30,
    },
}


@pytest.fixture
def ride():
    return json.loads((FIXTURES / "special-ride.json").read_text())


@pytest.fixture
def race():
    event = json.loads((FIXTURES / "race.json").read_text())
    event["name"] = "Synthetic open race"
    event["accessExpression"] = None
    for g in event["eventSubgroups"]:
        g["rangeAccessLabel"] = None
        g["accessRules"] = []
    return event


def choose(event, profile=PROFILE):
    return select(
        [event], profile, instant(event["eventStart"]) - timedelta(minutes=1)
    )[0]


def test_shortest_special_ride_from_live_label(ride):
    rows = choose(ride)
    assert len(rows) == 1
    assert rows[0]["group_name"].startswith("Short -")
    assert rows[0]["band"] is None
    assert rows[0]["event_kind"] == "special_ride"
    assert rows[0]["special_event"] == "Tour of Watopia"


def test_shortest_eligible_route_checks_gender_and_other_restrictions(ride):
    ride["eventSubgroups"][2]["rulesSet"] = ["LADIES_ONLY"]
    assert choose(ride)[0]["group_name"].startswith("Standard -")
    ride["eventSubgroups"][1]["accessValidationResult"] = False
    assert choose(ride)[0]["group_name"].startswith("Long -")


def test_shortest_uses_distances_not_laps_on_different_routes(ride):
    for i, group in enumerate(ride["eventSubgroups"]):
        group["name"] = f"Route choice {i}"
        group["distanceInMeters"] = [12000, 6000, 9000][i]
        group["laps"] = [1, 3, 2][i]
    assert choose(ride)[0]["subgroup_id"] == ride["eventSubgroups"][1]["id"]
    for group in ride["eventSubgroups"]:
        group["distanceInMeters"] = 0
    rows, excluded = select([ride], PROFILE, instant(ride["eventStart"]))
    assert rows == [] and excluded["shortest_route_unknown"] == 1


@pytest.mark.parametrize("event_type", ["GROUP_WORKOUT", "RUNNING_RACE", "MEETUP"])
def test_other_special_event_types_stay_excluded(ride, event_type):
    ride["eventType"] = event_type
    assert choose(ride) == []


def test_ordinary_club_ride_and_running_excluded(ride):
    ordinary = copy.deepcopy(ride)
    ordinary.update(
        name="Friendly weekly club ride", tags=[], eventSeries={"name": "Weekly rides"}
    )
    assert choose(ordinary) == []
    ride["sport"] = "RUNNING"
    assert choose(ride) == []


def test_recognized_campaigns_and_no_generic_series_match():
    assert campaign({"tags": ["tourofwatopia2026ride"]}) == "Tour of Watopia"
    assert campaign({"tags": ["tdz2026"]}) == "Tour de Zwift"
    assert (
        campaign({"eventSeries": {"name": "Zwift Games 2026 Stage 1"}}) == "Zwift Games"
    )
    assert campaign({"name": "Stage 1 - The Zwift Big Spin"}) == "Zwift Big Spin"
    assert (
        campaign(
            {
                "name": "Special club ride",
                "eventSeries": {"name": "Weekly racing series"},
            }
        )
        is None
    )


def test_open_race_without_score_does_not_need_a_provisional_band(race):
    profile = PROFILE | {"current": None, "max30": None}
    rows = choose(race, profile)
    assert len(rows) == 1 and rows[0]["band"] is None
    assert rows[0]["provisional"] is False
    for group, pace in zip(race["eventSubgroups"], [5, 4, 3, 2, 0], strict=True):
        group["toPaceValue"] = pace
    assert choose(race)[0]["subgroup_id"] == race["eventSubgroups"][3]["id"]


def test_legacy_category_requires_server_confirmation(race):
    race["accessExpression"] = "powerCurves.category >= subgroup.label"
    race["categoryEnforcement"] = True
    assert choose(race) == []
    for group in race["eventSubgroups"]:
        group["accessValidationResult"] = False
    allowed = race["eventSubgroups"][3]
    allowed["accessValidationResult"] = True
    assert choose(race)[0]["subgroup_id"] == allowed["id"]
    allowed["accessRules"] = [{"name": "another requirement", "result": False}]
    assert choose(race) == []


def test_unbanded_restrictions_never_treated_as_open(race):
    race["categoryEnforcement"] = True
    assert choose(race) == []
    race["categoryEnforcement"] = False
    race["accessExpression"] = "profile.male == false"
    assert choose(race) == []
    race["accessExpression"] = None
    race["privateEvent"] = True
    assert choose(race) == []


def test_max_suffix_retains_score_filtering(race):
    race["accessExpression"] = "scoring.max30 < 160"
    for g in race["eventSubgroups"]:
        g["rangeAccessLabel"] = "0-160 Max"
    assert choose(race)[0]["score_basis"] == "max30"
    assert choose(race, PROFILE | {"max30": 200}) == []
    race["accessExpression"] = "scoring.current < 160"
    assert choose(race) == []


def test_absent_band_is_not_malformed_band(race):
    for g in race["eventSubgroups"]:
        g["rangeAccessLabel"] = "not a valid band"
    assert choose(race) == []


def test_unbanded_calendar_description_and_stable_uid(ride):
    events = choose(ride)
    events[0]["duration"] = estimate(events[0], {}, 100)
    now = instant(ride["eventStart"])
    snapshot, revisions = reconcile(events, {}, now)
    parsed = vobject.readOne(snapshot["ics"]).vevent
    assert "No score band" in parsed.summary.value
    assert "Shortest eligible ride option: Short -" in parsed.description.value
    assert "Racing Score band None" not in parsed.description.value
    assert "beginner pace" in parsed.description.value
    second, _ = reconcile(events, revisions, now + timedelta(hours=1))
    assert second["etag"] == snapshot["etag"]


def test_special_rides_do_not_consume_race_history_budget(ride):
    from unittest.mock import Mock

    api = Mock()
    learn(api, [ride], choose(ride), {}, 100, instant(ride["eventStart"]))
    api.event.assert_not_called()
    api.results.assert_not_called()


def test_weekly_counts_do_not_double_count_boundary_or_campaign_races():
    now = datetime(2026, 10, 9, tzinfo=UTC)
    rows = [
        {
            "start": now.isoformat(),
            "band": "0-160",
            "event_kind": "race",
            "special_event": "Tour of Watopia",
        },
        {
            "start": (now + timedelta(days=1)).isoformat(),
            "band": None,
            "event_kind": "race",
        },
        {
            "start": (now + timedelta(days=7)).isoformat(),
            "band": None,
            "event_kind": "special_ride",
        },
        {
            "start": (now + timedelta(days=14)).isoformat(),
            "band": None,
            "event_kind": "special_ride",
        },
    ]
    first, second = weekly_counts(rows, now)
    assert (
        first["total"] == 2
        and first["score_banded_races"] == 1
        and first["unbanded_races"] == 1
    )
    assert second["total"] == 1 and second["special_event_rides"] == 1


@pytest.mark.parametrize("expression", [False, 0, {}])
def test_malformed_expression_is_not_unrestricted(race, expression):
    race["accessExpression"] = expression
    assert choose(race) == []


def test_mixed_unknown_route_labels_do_not_claim_shortest(ride):
    ride["eventSubgroups"][0]["name"] = "Unknown route option"
    assert choose(ride) == []
