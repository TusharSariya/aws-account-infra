import copy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3
import pytest
import vobject
from moto import mock_aws

from iracing_calendar import feed
from iracing_calendar.reconcile import reconcile
from iracing_calendar.schedule import occurrences, race_slots
from iracing_calendar.sources import (
    Fetcher,
    deduplicate,
    literal_array,
    special_starts,
    weekly_overrides,
)
from iracing_calendar.store import Conflict, Store
from iracing_calendar.sync import health, refresh

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
SERIES = {
    "name": "Example - 2026 Season 4",
    "category": "SPORTS CAR",
    "cars": "GT3",
    "license": "Class C",
    "frequency": "Races every other Saturday at 4 & 15 GMT and Sunday at 0 GMT, 20 GMT",
    "sources": ["https://iracinghub.com/"],
    "weeks": [
        {"week": 1, "date": "2026-09-26", "track": "Road Atlanta", "laps": "20 laps"},
        {"week": 2, "date": "2026-10-10", "track": "Daytona", "laps": "120 mins"},
    ],
}


def snapshot(series=None, old=None, now=NOW):
    incoming = occurrences(series or SERIES)
    return reconcile(old or {}, incoming, ["series:2026 Season 4"], now)


@pytest.mark.parametrize(
    "frequency",
    [
        "Races every hour at :15",
        "Races every 30 minutes",
        "Races every odd 2 hours on the hour",
        "Races 45 past every 2 hours",
        "Open Qualifier every 30 mins at :15 & :45 past",
    ],
)
def test_exclude_continuous_and_non_races(frequency):
    assert race_slots(frequency) == []


def test_alternating_weeks_and_cross_midnight():
    events = occurrences(SERIES)
    assert len(events) == 8
    assert {e["start"][:10] for e in events} == {
        "2026-09-26",
        "2026-09-27",
        "2026-10-10",
        "2026-10-11",
    }
    midnight = next(e for e in events if e["start"] == "2026-09-27T00:00:00+00:00")
    assert (
        datetime.fromisoformat(midnight["start"])
        .astimezone(ZoneInfo("America/St_Johns"))
        .isoformat()
        == "2026-09-26T21:30:00-02:30"
    )
    assert events[0]["end"] is None
    assert events[4]["end"] == "2026-10-10T06:00:00+00:00"


def test_newfoundland_dst():
    tz = ZoneInfo("America/St_Johns")
    assert datetime(2026, 10, 31, 14, tzinfo=UTC).astimezone(tz).hour == 11
    assert datetime(2026, 11, 1, 14, tzinfo=UTC).astimezone(tz).hour == 10


def test_shared_days_and_all_starts():
    assert len(race_slots("Races Thur & Sat at 10, 19 GMT & Fri & Sun at 1,4 GMT")) == 8
    assert len(race_slots("Races on Wednesday and Saturdays at 14 and 19 GMT")) == 4
    with pytest.raises(ValueError):
        race_slots("Races on an unpublished schedule")


def test_revisions_corrections_cancellations_rollover():
    first = snapshot()
    same = snapshot(old=first, now=NOW + timedelta(days=7))
    assert first["ics"] == same["ics"] and first["etag"] == same["etag"]
    corrected = copy.deepcopy(SERIES)
    corrected["weeks"][0]["track"] = "Road Atlanta - Full Course"
    revised = snapshot(corrected, first)
    assert [e["sequence"] for e in revised["events"]] == [1] * 4 + [0] * 4
    corrected["weeks"].pop()
    cancelled = snapshot(corrected, revised)
    assert cancelled["report"]["removed"] == 4
    rollover = reconcile(first, [], ["series:2027 Season 1"], NOW)
    assert rollover["ics"] == first["ics"]


def test_placeholder_replacement_and_independent_ics():
    unknown = SERIES | {"frequency": "4 Timeslots Per Week"}
    initial = snapshot(unknown)
    cal = vobject.readOne(initial["ics"])
    event = cal.vevent_list[0]
    assert event.dtstart.value == date(2026, 9, 26)
    assert event.dtend.value == date(2026, 9, 29)
    assert event.transp.value == "TRANSPARENT"
    assert "Start times unconfirmed" in event.summary.value
    verified = snapshot(SERIES, initial)
    confirmed = vobject.readOne(verified["ics"])
    assert confirmed.vevent_list[0].uid.value == event.uid.value
    assert confirmed.vevent_list[0].sequence.value == "1"
    assert not hasattr(confirmed.vevent_list[0], "dtend")
    assert not hasattr(confirmed.vevent_list[0], "valarm")
    assert vobject.readOne(reconcile({}, [], [], NOW)["ics"]).name == "VCALENDAR"


def test_retention():
    assert not snapshot(now=NOW + timedelta(days=90))["events"]


def test_literal_data_never_executes():
    assert (
        literal_array('const x=[{category:"OVAL",name:"race",weeks:[]}];alert("bad")')[
            0
        ]["name"]
        == "race"
    )
    with pytest.raises(ValueError):
        literal_array('const x=[{category:"OVAL",name:(function(){return "bad"})()}]')


def test_weekly_fixture():
    body = Path("tests/fixtures/weekly.html").read_text()
    overrides = weekly_overrides(body, "https://www.iracing.com/weekly")
    assert len(overrides[("NASCAR iRacing Series Fixed", "2026-09-22")][0]) == 5
    series = SERIES | {
        "name": "NASCAR iRacing Series - 2026 Season Fixed",
        "frequency": "5 Timeslots Per Week",
    }
    events = occurrences(series, overrides)
    assert sum(not e["all_day"] for e in events) == 5
    assert sum(e["all_day"] for e in events) == 1


def test_special_dedup():
    events = occurrences(SERIES | {"name": "NASCAR iRacing Series - 2026 Season Fixed"})
    special = {
        "name": "Southern 500",
        "start": "2026-09-26",
        "description": "Special",
        "sources": ["https://www.iracing.com/special-events/"],
    }
    assert len(deduplicate(events, [special])) == 8
    assert "Special" in events[0]["description"]


def test_special_published_start_not_sim_time():
    item = {
        "name": "Petit Le Mans",
        "start": "2026-09-25",
        "end": "2026-09-28",
        "round_id": "special:2026:petit",
        "sources": [],
    }
    events = [item]
    special_starts(
        events,
        "<h1>THIS WEEK: Petit Le Mans</h1><h3>ABOUT THE 2026 EVENT</h3><p>Timeslot #1: Friday at 22:00 GMT</p><p>Simulated October 3 at 10:55</p>",
        "https://www.iracing.com/event",
    )
    assert events[0]["start"] == "2026-09-25T22:00:00+00:00"


@pytest.fixture
def store(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        monkeypatch.setenv("SNAPSHOT_BUCKET", "calendar-test")
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket="calendar-test")
        yield Store(s3, "calendar-test", clock=lambda: NOW.timestamp())


def test_feed_initialization_conditional_and_read_only(store, monkeypatch):
    monkeypatch.setattr(feed, "Store", lambda: store)
    assert feed.lambda_handler({}, None)["statusCode"] == 503
    data = snapshot()
    store.write(data)
    assert feed.lambda_handler({}, None)["body"] == data["ics"]
    for tag in [data["etag"], "W/" + data["etag"], '"other", ' + data["etag"], "*"]:
        assert (
            feed.lambda_handler({"headers": {"If-None-Match": tag}}, None)["statusCode"]
            == 304
        )
    assert store.read()[0] == data


def test_fenced_lease_atomic_publish_and_recovery(store):
    previous = snapshot()
    store.write(previous)
    state, version, owner = store.claim()
    assert store.read()[0]["ics"] == previous["ics"]
    with pytest.raises(Conflict):
        store.claim()
    store.clock = lambda: NOW.timestamp() + 601
    newer, new_version, new_owner = store.claim()
    with pytest.raises(Conflict):
        store.publish(state, version, owner)
    # The stale worker also cannot release a new worker's lease.
    store.release(version, owner)
    assert store.read()[0]["lease"] == new_owner
    store.publish(newer, new_version, new_owner)
    assert "lease" not in store.read()[0]


def test_source_failure_preserves_snapshot(store):
    previous = snapshot()
    store.write(previous)

    def broken(*args):
        raise ValueError("unrecognized source")

    with pytest.raises(ValueError):
        refresh(store, NOW, broken)
    assert store.read()[0] == previous


def test_refresh_and_busy(store):
    def extractor(*args):
        return occurrences(SERIES), ["series:2026 Season 4"], {}

    result = refresh(store, NOW, extractor)
    assert result["timed"] == 8 and result["status"] == "ok"
    store.claim()
    assert refresh(store, NOW, extractor) == {"status": "busy"}


def test_health_does_not_fetch_sources(store, monkeypatch):
    store.write(snapshot())
    assert health(store, NOW)["report"]["timed"] == 8
    with pytest.raises(RuntimeError):
        health(store, NOW + timedelta(days=8, seconds=1))


def test_source_allowlist_and_request_bound():
    fetch = Fetcher()
    with pytest.raises(ValueError):
        fetch.get("http://127.0.0.1/")
    fetch.requests = 24
    with pytest.raises(ValueError):
        fetch.get("https://iracinghub.com/")


def test_adding_and_removing_slots_preserves_other_uids():
    first = snapshot()
    series = SERIES | {
        "frequency": "Races Saturday at 3, 4, 15 GMT and Sunday at 0, 20 GMT"
    }
    added = snapshot(series, first)
    old_ids = {e["start"]: e["id"] for e in first["events"]}
    assert all(
        e["id"] == old_ids[e["start"]] for e in added["events"] if e["start"] in old_ids
    )
    removed = snapshot(SERIES, added)
    assert {e["start"]: e["id"] for e in removed["events"]} == old_ids


def test_daily_schedule_and_unknown_qualifier():
    assert len(race_slots("Races daily at 19 GMT")) == 7
    with pytest.raises(ValueError):
        race_slots("Races Saturday at 19 GMT except holidays")


def test_source_cache_validators(monkeypatch):
    import base64
    from urllib.error import HTTPError

    from iracing_calendar import sources

    url = "https://iracinghub.com/"
    cached = {"body": base64.b64encode(b"literal data").decode(), "etag": '"abc"'}
    fetch = Fetcher({url: cached})

    def unchanged(request, timeout):
        assert request.get_header("If-none-match") == '"abc"'
        raise HTTPError(url, 304, "Not modified", {}, None)

    monkeypatch.setattr(sources, "urlopen", unchanged)
    assert fetch.get(url) == b"literal data"
    assert fetch.used[url] == cached


def test_incomplete_special_times_fail_closed():
    events = [
        {
            "name": "Petit Le Mans",
            "start": "2026-09-25",
            "end": "2026-09-28",
            "round_id": "special:2026:petit",
            "sources": [],
        }
    ]
    with pytest.raises(ValueError):
        special_starts(
            events,
            "<h1>Petit Le Mans</h1><p>ABOUT THE 2026 EVENT</p><p>Timeslot #1: Friday at 22:00 GMT</p><p>Timeslot #2: Saturday TBD</p>",
            "https://www.iracing.com/event",
        )


def test_official_pdf_completeness_and_simulated_track_time(monkeypatch):
    from iracing_calendar import sources

    names = [f"Series {i} - 2026 Season 4" for i in range(80)]
    toc = "\n".join(name + " . . . 6" for name in names)
    block = "\nOVAL\nC Class Series (OVAL)\n" + "\n".join(
        name + "\nGT3\nClass C 4.0 --> Pro/WC 4.0\nRaces Saturday at 19 GMT\n"
        "Week 1 (2026-09-22)    Test Circuit - Grand    Rolling start, 20 laps\n"
        "                       Prix                    Cautions enabled\n"
        "                       (2024-01-01 12:00 1x)\n"
        for name in names
    )

    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self, **kwargs):
            return self.text

    class Reader:
        pages = [Page(toc), Page(block)] + [Page("")] * 48

    monkeypatch.setattr(sources, "PdfReader", lambda body: Reader())
    hub = [SERIES | {"name": name, "category": "OVAL"} for name in names]
    official = sources.official_series(b"fixture", hub)
    first = official[0]
    assert first["weeks"][0]["track"] == "Test Circuit - Grand Prix"
    assert occurrences(first)[0]["start"] == "2026-09-26T19:00:00+00:00"
    Reader.pages[1] = Page(block[: block.index(names[-1])])
    with pytest.raises(ValueError, match="table of contents"):
        sources.official_series(b"truncated fixture", hub)
