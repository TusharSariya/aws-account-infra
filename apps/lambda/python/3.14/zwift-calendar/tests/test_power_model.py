import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from zwift_calendar.course import resolve, routes
from zwift_calendar.physics import (
    MODEL,
    coarse,
    forces,
    rider_cda,
    speed_for_power,
    travel,
)
from zwift_calendar.power import PowerCurve, recording_curve, weight
from zwift_calendar.prediction import predict, reserve

NOW = datetime(2026, 10, 12, tzinfo=UTC)
BODY = {"weight_kg": 75, "height_cm": 183}


def activity(age, curve):
    return {"completed": (NOW - timedelta(days=age)).isoformat(), "curve": curve}


@pytest.mark.parametrize(
    "days,expected",
    [
        (0, 1),
        (6.9999, 1),
        (7, 0.75),
        (13.9999, 0.75),
        (14, 0.5),
        (20.9999, 0.5),
        (21, 0.25),
        (27.9999, 0.25),
        (28, 0),
        (40, 0),
        (-1, 0),
    ],
)
def test_exact_recency_boundaries(days, expected):
    assert weight(activity(days, {})["completed"], NOW) == expected


def test_normalized_weights_differing_lengths_and_expiry():
    rows = [
        activity(0, {"60": 200, "120": 190, "600": 150}),
        activity(7, {"60": 100}),
        activity(21, {"60": 100, "120": 100}),
    ]
    curve = PowerCurve(rows, NOW)
    assert curve.watts(60) == 150
    assert curve.watts(120) == pytest.approx(150)  # monotone repair
    assert curve.watts(600) == pytest.approx(150)
    assert curve.counts == {60: 3, 120: 2, 600: 1}
    assert curve.evidence(600)["activities"] == 1
    assert PowerCurve(rows, NOW + timedelta(days=28)).default
    unchanged = PowerCurve([activity(21, {"60": 200})], NOW)
    assert unchanged.watts(60) == 200  # quarter weight is not quarter wattage


def records(values, start=NOW):
    return [
        {"timestamp": start + timedelta(seconds=i), "power": p}
        for i, p in enumerate(values)
    ]


def test_max_sustained_coasting_pauses_and_gaps():
    assert recording_curve(records([200] * 30 + [0] * 30)) == {"60": 100}
    assert recording_curve(records([100] * 60 + [200] * 60)) == {"60": 200, "120": 150}
    assert (
        recording_curve(
            records([200] * 59) + records([200] * 59, NOW + timedelta(seconds=61))
        )
        == {}
    )
    assert recording_curve(records([200] * 59 + [None] + [200] * 59)) == {}
    messages = (
        records([200] * 40)
        + [{"kind": "event", "event": "timer", "event_type": "stop_all"}]
        + records([500] * 80, NOW + timedelta(seconds=40))
    )
    messages += [{"kind": "event", "event": "timer", "event_type": "start"}] + records(
        [100] * 60, NOW + timedelta(seconds=120)
    )
    assert recording_curve(messages) == {"60": 100}


def test_default_interpolation_and_endurance_without_second_penalty():
    curve = PowerCurve([], NOW)
    for seconds, watts in [
        (60, 120),
        (300, 120),
        (1200, 105),
        (3600, 100),
        (7200, 90),
        (14400, 80),
    ]:
        assert curve.watts(seconds) == pytest.approx(watts)
    assert curve.watts(math.sqrt(300 * 1200)) == pytest.approx(math.sqrt(120 * 105))
    assert curve.watts(28800) == pytest.approx(80 * (80 / 90))
    assert curve.evidence(3600)["power_source"] == "default"
    short = PowerCurve([activity(0, {"60": 200})], NOW)
    assert short.watts(600) == pytest.approx(200 * 10**-0.1)
    assert short.evidence(600)["assumed_endurance_exponent"]
    steep = PowerCurve([activity(0, {"600": 400, "1200": 100})], NOW)
    assert steep.exponent == 0.5
    assert steep.watts(2400) == pytest.approx(100 * 2**-0.5)


def test_upstream_executable_force_reference():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/force-reference.json").read_text()
    )
    assert fixture["commit"] == MODEL["commit"]
    for r in fixture["cases"]:
        cda = rider_cda(r["height"], r["weight"])
        assert cda == pytest.approx(r["cda"], rel=1e-12)
        assert forces(
            r["v"], r["grade"], r["power"], r["weight"], cda, r["surface"]
        ) == pytest.approx(r["forces"], rel=1e-12)
        assert speed_for_power(
            r["power"], r["weight"] + 8, r["grade"], MODEL["crr"][r["surface"]], cda
        ) == pytest.approx(r["speed"], rel=1e-12)


def test_flat_climb_descent_and_acceleration():
    times = [travel([(1000, rise, "tarmac")], 150, 75, 183) for rise in (0, 80, -80)]
    assert times[1] > times[0] > times[2]
    steady = 1000 / speed_for_power(150, 83, 0, 0.004, rider_cda(183, 75))
    assert times[0] > steady
    assert travel([(1000, 0, "tarmac")], 150, 75, 183, step=0.25) == pytest.approx(
        times[0], rel=0.002
    )
    hills = travel([(500, 50, "tarmac"), (500, -50, "tarmac")], 150, 75, 183)
    assert hills > times[0]  # zero net elevation doesn't erase the hill
    assert coarse(1000, 80, 150, 75, 183) > coarse(1000, 0, 150, 75, 183)


def test_laps_lead_once_distance_target_and_direction():
    catalog = {
        "1": {
            "distance": 1000,
            "ascent": 20,
            "lead_distance": 100,
            "lead_ascent": 5,
            "lap": True,
            "segments": [(500, 20, "tarmac"), (500, -20, "dirt")],
        }
    }
    event = {"signature": [1, 0, 3, "RACE"]}
    course = resolve(event, catalog)
    assert course["distance"] == 3100
    assert len(course["segments"]) == 6
    assert course["coarse_distance"] == 100 and course["coarse_ascent"] == 5
    clipped = resolve({"signature": [1, 850, 3, "RACE"]}, catalog)
    assert clipped["segments"] == [(500, 20, "tarmac"), (250, -10, "dirt")]
    assert clipped["distance"] == 850
    reverse = resolve(event | {"course": {"reverse": True}}, catalog)
    assert reverse["segments"] == [] and reverse["coarse_ascent"] == 0
    catalog["1"]["lap"] = False
    with pytest.raises(ValueError):
        resolve(event, catalog)
    assert (
        "elevation unavailable"
        in resolve({"signature": [None, 1000, 0, "RACE"]}, catalog)["course_source"]
    )


def test_all_bundled_profiles_are_finite_and_cover_route():
    assert len(routes()) >= 290
    for route in routes().values():
        if route.get("segments"):
            assert sum(s[0] for s in route["segments"]) == pytest.approx(
                route["distance"], abs=0.2
            )
            assert all(
                s[0] > 0 and math.isfinite(s[1]) and s[2] in MODEL["crr"]
                for s in route["segments"]
            )


def test_default_prediction_missing_course_and_conservative_reservation():
    event = {"signature": [None, 10000, 0, "RACE"]}
    prediction = predict(event, PowerCurve([], NOW), BODY, {})
    assert prediction["category"] == "default" and prediction["seconds"] != 3600
    assert "100 W FTP-based default" in prediction["source"]
    assert prediction["margin"] == 0.4
    assert prediction["reserved_seconds"] % 300 == 0
    assert (
        prediction["reserved_seconds"]
        >= prediction["upper_seconds"]
        > prediction["seconds"]
    )
    assert (
        predict({"signature": [None, 0, 0, "RACE"]}, PowerCurve([], NOW), BODY, {})[
            "seconds"
        ]
        is None
    )
    assert predict(event, PowerCurve([], NOW), {}, {})["seconds"] is None
    # An actual model result of exactly one hour remains valid.
    assert reserve({"seconds": 3600}, 0.2)["reserved_seconds"] == 4500


def test_measured_profile_margin_and_extrapolated_uncertainty(monkeypatch):
    from zwift_calendar import prediction

    monkeypatch.setattr(
        prediction,
        "resolve",
        lambda e: {
            "segments": [(1000, 0, "tarmac")],
            "coarse_distance": 0,
            "coarse_ascent": 0,
            "distance": 1000,
            "course_source": "elevation profile",
        },
    )
    rows = [activity(i, {"60": 200, "600": 180}) for i in range(3)]
    estimate = predict({}, PowerCurve(rows, NOW), BODY, {})
    assert estimate["category"] == "measured" and estimate["margin"] == 0.2
    assert estimate["activities"] == 3
    sparse = predict({}, PowerCurve(rows[:1], NOW), BODY, {})
    assert sparse["sparse"] and sparse["margin"] == 0.4
    incomplete = predict(
        {}, PowerCurve(rows, NOW), BODY, {"collection_incomplete": True}
    )
    assert incomplete["margin"] == 0.4 and incomplete["collection_incomplete"]
    short = predict({}, PowerCurve([activity(0, {"60": 200})], NOW), BODY, {})
    assert short["category"] == "extrapolated" and short["margin"] == 0.4


def test_optional_end_revision_transition_and_private_power_not_rendered():
    from icalendar import Calendar

    from zwift_calendar.calendar import reconcile
    from zwift_calendar.prediction import unavailable

    row = {
        "id": "1-2",
        "name": "★ Special",
        "start": NOW.isoformat(),
        "band": None,
        "group": "D",
        "url": "https://www.zwift.com/events/view/1",
        "signature": [None, 10000, 0, "RACE"],
        "requirements": [],
        "provisional": False,
        "time_trial": False,
        "duration": unavailable("course distance unavailable"),
    }
    first, revisions = reconcile([row], {}, NOW)
    event = Calendar.from_ical(first["ics"]).walk("VEVENT")[0]
    assert "DTEND" not in event and "DURATION" not in event
    assert str(event["SUMMARY"]).startswith("★")
    same, _ = reconcile([row], revisions, NOW + timedelta(hours=1))
    assert same["etag"] == first["etag"]
    row["duration"] = predict(row, PowerCurve([], NOW), BODY, {})
    second, revisions = reconcile([row], revisions, NOW + timedelta(hours=1))
    event = Calendar.from_ical(second["ics"]).walk("VEVENT")[0]
    assert int(event["SEQUENCE"]) == 1
    assert (event.decoded("DTEND") - event.decoded("DTSTART")).total_seconds() == row[
        "duration"
    ]["reserved_seconds"]
    assert int(event["X-ZWIFT-EXPECTED-DURATION-SECONDS"]) == row["duration"]["seconds"]
    assert "weight_kg" not in second["ics"] and "height_cm" not in second["ics"]
    row["duration"] = unavailable("course distance unavailable")
    third, _ = reconcile([row], revisions, NOW + timedelta(hours=2))
    event = Calendar.from_ical(third["ics"]).walk("VEVENT")[0]
    assert "DTEND" not in event and int(event["SEQUENCE"]) == 2


@pytest.mark.parametrize(
    "points",
    [
        [],
        [(60, 100)],
        [(60, 100), (60, 90)],
        [(60, 100), (120, 110)],
        [(60, float("nan")), (120, 90)],
    ],
)
def test_invalid_default_configuration_is_rejected(points):
    with pytest.raises(ValueError):
        PowerCurve([], NOW, points)


def test_interpolation_reports_all_contributors_and_weakest_duration_support():
    curve = PowerCurve(
        [
            activity(0, {"60": 200, "120": 100}),
            activity(1, {"60": 200}),
            activity(2, {"60": 200}),
        ],
        NOW,
    )
    evidence = curve.evidence(90)
    assert evidence["activities"] == 3
    assert (
        evidence["duration_support_min"] == 1 and evidence["duration_support_max"] == 3
    )
    assert evidence["sparse"]
