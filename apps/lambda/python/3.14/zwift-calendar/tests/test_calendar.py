import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import vobject

from zwift_calendar.api import instant, score_value
from zwift_calendar.calendar import reconcile
from zwift_calendar.duration import estimate, histogram
from zwift_calendar.errors import ContractError, UnsupportedRule
from zwift_calendar.filtering import select
from zwift_calendar.rules import evaluate, parse
from zwift_calendar.service import serve

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def race():
    event = json.loads((FIXTURES / "race.json").read_text())
    event["name"] = "Synthetic scored race"
    return event


@pytest.fixture
def profile():
    return {
        "current": 100,
        "max30": 100,
        "fields": {
            "profile.playerType": "NORMAL",
            "profile.profileId": 1,
            "profile.age": 30,
            "profile.male": True,
        },
    }


def selected(race, profile):
    return select([race], profile, instant(race["eventStart"]) - timedelta(minutes=1))[
        0
    ]


def test_real_subgroup_start_and_score_band(race, profile):
    event = selected(race, profile)[0]
    group = next(g for g in race["eventSubgroups"] if g["rangeAccessLabel"] == "0-160")
    assert event["subgroup_id"] == group["id"]
    assert instant(event["start"]) == instant(group["eventSubgroupStart"])
    assert event["band"] == "0-160"


def test_boundary_and_max30(race, profile):
    profile["current"] = 160
    assert selected(race, profile)[0]["band"] == "160-270"
    race["accessExpression"] = race["accessExpression"].replace(
        "scoring.current", "scoring.max30"
    )
    profile.update(current=100, max30=300)
    assert selected(race, profile)[0]["band"] == "270-390"


def test_missing_score_is_provisional_not_zero(race, profile):
    profile.update(current=None, max30=None)
    assert selected(race, profile)[0]["provisional"] is True
    profile.update(current=0, max30=0)
    assert selected(race, profile)[0]["provisional"] is False
    assert score_value({"scores": {}}) is None
    with pytest.raises(ContractError):
        score_value({})


@pytest.mark.parametrize("value", [False, "100", -1, 1001, float("nan")])
def test_invalid_score(value):
    with pytest.raises(ContractError):
        score_value({"scores": {"ZWIFT_PUBLIC_SCORE": {"value": value}}})


@pytest.mark.parametrize(
    "expression",
    [
        '__import__("os")',
        "profile.unknown == 1",
        "scoring.current < 100; true",
        "(" * 40 + "true" + ")" * 40,
    ],
)
def test_rules_never_execute(expression):
    with pytest.raises(UnsupportedRule):
        parse(expression)


def test_rule_precedence_and_unknown_branch():
    assert evaluate(parse("false || true && 100 < 160"), {}) is True
    with pytest.raises(UnsupportedRule):
        evaluate(parse("true || scoring.max30 > 100"), {})


def test_restricted_and_unknown_events(race, profile):
    for key, value in [
        ("privateEvent", True),
        ("sport", "RUNNING"),
        ("eventType", "GROUP_WORKOUT"),
        ("accessExpression", "powerCurves.category == 1"),
    ]:
        item = copy.deepcopy(race)
        item[key] = value
        assert selected(item, profile) == []
    race["rulesSet"] = ["LADIES_ONLY"]
    assert selected(race, profile) == []


def test_horizon_uses_subgroup_not_parent(race, profile):
    start = instant(
        next(g for g in race["eventSubgroups"] if g["rangeAccessLabel"] == "0-160")[
            "eventSubgroupStart"
        ]
    )
    assert select([race], profile, start - timedelta(days=14))[0] == []
    assert len(select([race], profile, start)[0]) == 1
    assert select([race], profile, start + timedelta(seconds=1))[0] == []


def test_tt_and_ics_revisions(race, profile):
    race["eventType"] = "TIME_TRIAL"
    events = selected(race, profile)
    events[0]["name"] = "Café, race; with\\line\nSecond line " * 6
    events[0]["duration"] = estimate(events[0], {}, 100)
    now = instant(race["eventStart"])
    snapshot, revisions = reconcile(events, {}, now)
    parsed = vobject.readOne(snapshot["ics"])
    assert parsed.vevent.uid.value.endswith("@zwift-calendar")
    assert "session opening" in parsed.vevent.description.value
    same, _ = reconcile(events, revisions, now + timedelta(hours=1))
    assert same["etag"] == snapshot["etag"]
    events[0]["duration"]["seconds"] = 2400
    changed, _ = reconcile(events, revisions, now + timedelta(hours=2))
    revised = vobject.readOne(changed["ics"])
    assert revised.vevent.uid.value == parsed.vevent.uid.value
    assert revised.vevent.sequence.value == "1"
    empty, _ = reconcile([], revisions, now)
    assert not hasattr(vobject.readOne(empty["ics"]), "vevent")


def test_estimate_requires_comparable_samples(race, profile):
    event = selected(race, profile)[0]
    sample = {
        "signature": event["signature"],
        "bins": [[100, 2400, 5], [200, 1000, 100]],
    }
    history = {"races": {"1": {"samples": [sample]}, "2": {"samples": [sample]}}}
    assert estimate(event, history, 100)["seconds"] == 2400
    history["races"].pop("2")
    assert estimate(event, history, 100)["seconds"] == 3600
    event["published_seconds"] = 1800
    assert estimate(event, history, 100)["seconds"] == 1800


def test_results_are_anonymized_and_filtered():
    row = {
        "profileId": 1,
        "eventSubgroupId": 2,
        "qualified": True,
        "rank": 1,
        "profileData": {"firstName": "Never store"},
        "scoreHistory": {"previousScore": 100},
        "activityData": {"durationInMilliseconds": 2000000},
    }
    assert histogram([row, row, row | {"profileId": 3, "qualified": False}], 2) == [
        [100, 2000, 1]
    ]


def test_feed_conditional_and_initialization():
    class Store:
        def __init__(self):
            self.data = {}

        def read(self):
            return self.data, None

    store, now = Store(), datetime.now(UTC)
    event = {"routeKey": "GET /calendars/zwift-banded.ics"}
    assert serve(event, store, now)["statusCode"] == 503
    store.data = {
        "calendars": {
            key: {"ics": "calendar", "etag": '"abc"'} for key in ("banded", "unbanded")
        },
        "last_success": now.timestamp(),
    }
    assert (
        serve(event | {"headers": {"If-None-Match": 'W/"abc"'}}, store, now)[
            "statusCode"
        ]
        == 304
    )
    assert serve({"routeKey": "GET /wrong"}, store, now)["statusCode"] == 404
    with pytest.raises(RuntimeError):
        serve({"health": True}, store, now + timedelta(hours=4))


def test_authenticated_group_checks_and_malformed_band(race, profile):
    group = next(g for g in race["eventSubgroups"] if g["rangeAccessLabel"] == "0-160")
    group.update(
        accessRules=[{"name": "scored.race", "result": True}],
        accessValidationResult=True,
    )
    assert len(selected(race, profile)) == 1
    group["accessValidationResult"] = False
    assert selected(race, profile) == []
    group["accessValidationResult"] = True
    group["accessRules"] = [{"name": "unknown", "result": True}]
    assert selected(race, profile) == []
    group["accessRules"] = []
    group["rangeAccessLabel"] = "0-0"
    assert selected(race, profile) == []


def test_individual_tt_excludes_team_settings(race, profile):
    race["eventType"] = "TIME_TRIAL"
    race["timeTrialOptions"] = {"teamTimeTrial": True}
    assert selected(race, profile) == []


def test_utc_events_survive_newfoundland_dst(race, profile):
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/St_Johns")
    first = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
    rendered = []
    for start in (first, second):
        # Test UTC serialization independently of the overnight start filter.
        events = selected(race, profile)
        events[0]["start"] = start.astimezone(UTC).isoformat()
        now = start.astimezone(UTC) - timedelta(minutes=1)
        events[0]["duration"] = estimate(events[0], {}, 100)
        snapshot, _ = reconcile(events, {}, now)
        rendered.append(vobject.readOne(snapshot["ics"]).vevent.dtstart.value)
    assert rendered[1] - rendered[0] == timedelta(hours=1)
