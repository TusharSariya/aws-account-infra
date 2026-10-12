import copy
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
import vobject

from zwift_calendar.api import instant
from zwift_calendar.calendar import split_calendars
from zwift_calendar.filtering import select
from zwift_calendar.service import serve


@pytest.fixture
def sample():
    race = json.loads((Path(__file__).parent / "fixtures/race.json").read_text())
    race["name"] = "Synthetic eligible race"
    now = instant(race["eventStart"]) - timedelta(minutes=1)
    profile = {
        "current": 100,
        "max30": 100,
        "fields": {"profile.playerType": "NORMAL", "profile.male": True},
    }
    banded = select([race], profile, now)[0][0]
    banded["duration"] = {
        "seconds": None,
        "source": "finish time unavailable: course distance unavailable",
        "samples": 0,
    }
    unbanded = copy.deepcopy(banded) | {
        "id": "2-3",
        "event_id": 2,
        "subgroup_id": 3,
        "band": None,
    }
    return [banded, unbanded], now


def parse(feed):
    calendar = vobject.readOne(feed["ics"])
    return calendar, {
        event.uid.value: event for event in getattr(calendar, "vevent_list", [])
    }


def test_split_feeds_are_disjoint_named_and_complete(sample):
    events, now = sample
    snapshot, _ = split_calendars(events, {}, now)
    banded, banded_rows = parse(snapshot["calendars"]["banded"])
    unbanded, unbanded_rows = parse(snapshot["calendars"]["unbanded"])
    assert banded.contents["x-wr-calname"][0].value == "Zwift - Banded races"
    assert unbanded.contents["x-wr-calname"][0].value == "Zwift - Unbanded races"
    assert len(banded_rows) == len(unbanded_rows) == 1
    assert not banded_rows.keys() & unbanded_rows.keys()
    assert banded_rows.keys() | unbanded_rows.keys() == {
        e["id"] + "@zwift-calendar" for e in events
    }
    assert "profile" not in snapshot and "revisions" not in snapshot


def test_separate_etags_and_stable_revisions(sample):
    events, now = sample
    first, revisions = split_calendars(events, {}, now)
    same, revisions = split_calendars(events, revisions, now + timedelta(minutes=1))
    assert same["calendars"] == first["calendars"]
    events[1]["name"] = "Updated unbanded race"
    changed, _ = split_calendars(events, revisions, now + timedelta(minutes=2))
    assert changed["calendars"]["banded"] == first["calendars"]["banded"]
    assert (
        changed["calendars"]["unbanded"]["etag"]
        != first["calendars"]["unbanded"]["etag"]
    )
    _, rows = parse(changed["calendars"]["unbanded"])
    assert next(iter(rows.values())).sequence.value == "1"


def test_switching_band_moves_same_uid_without_duplicate(sample):
    events, now = sample
    _, revisions = split_calendars(events, {}, now)
    identity = events[0]["id"] + "@zwift-calendar"
    events[0]["band"] = None
    snapshot, _ = split_calendars(events, revisions, now + timedelta(minutes=1))
    assert parse(snapshot["calendars"]["banded"])[1] == {}
    _, rows = parse(snapshot["calendars"]["unbanded"])
    assert len(rows) == 2 and rows[identity].sequence.value == "1"


def test_unbanded_special_ride_stays_in_unbanded_feed(sample):
    events, now = sample
    events[1].update(
        event_kind="special_ride",
        special_event="Zwift Big Spin",
        group_name="Short ride",
    )
    snapshot, _ = split_calendars(events, {}, now)
    _, rows = parse(snapshot["calendars"]["unbanded"])
    assert (
        "Special event: Zwift Big Spin" in next(iter(rows.values())).description.value
    )


def test_routes_never_serve_other_feed_or_accept_other_etag(sample):
    events, now = sample
    snapshot, _ = split_calendars(events, {}, now)
    store = Mock()
    store.read.return_value = snapshot, None
    for key in ("banded", "unbanded"):
        feed = snapshot["calendars"][key]
        request = {"routeKey": f"GET /calendars/zwift-{key}.ics"}
        response = serve(request, store, now)
        assert response["body"] == feed["ics"]
        assert response["headers"]["Content-Disposition"].endswith(f'zwift-{key}.ics"')
        assert (
            serve(request | {"headers": {"if-none-match": feed["etag"]}}, store, now)[
                "statusCode"
            ]
            == 304
        )
        other = "unbanded" if key == "banded" else "banded"
        assert (
            serve(
                request
                | {"headers": {"if-none-match": snapshot["calendars"][other]["etag"]}},
                store,
                now,
            )["statusCode"]
            == 200
        )
    assert (
        serve({"routeKey": "GET /calendars/zwift.ics"}, store, now)["statusCode"] == 404
    )
    assert serve({"health": True}, store, now) == {"status": "ok"}
    snapshot["calendars"].pop("unbanded")
    assert (
        serve({"routeKey": "GET /calendars/zwift-unbanded.ics"}, store, now)[
            "statusCode"
        ]
        == 503
    )
    with pytest.raises(RuntimeError):
        serve({"health": True}, store, now)


def test_empty_calendars_are_valid_subscriptions(sample):
    _, now = sample
    snapshot, _ = split_calendars([], {}, now)
    assert all(parse(feed)[1] == {} for feed in snapshot["calendars"].values())


def test_preview_writes_two_files(sample, monkeypatch, tmp_path, capsys):
    from zwift_calendar import cli

    events, now = sample
    snapshot, _ = split_calendars(events, {}, now)
    monkeypatch.setattr(cli, "Store", Mock())
    monkeypatch.setattr(cli, "Parameters", Mock())
    monkeypatch.setattr(cli, "Transport", Mock())
    monkeypatch.setattr(
        cli,
        "refresh",
        Mock(return_value={"status": "ok", "calendars": snapshot["calendars"]}),
    )
    monkeypatch.setattr("sys.argv", ["zwift", "preview", "--output-dir", str(tmp_path)])
    assert cli.main() == 0
    for key, feed in snapshot["calendars"].items():
        assert (tmp_path / f"zwift-{key}.ics").read_bytes() == feed["ics"].encode()
    assert "BEGIN:VCALENDAR" not in capsys.readouterr().out
