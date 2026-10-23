import copy
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import boto3
import pytest
import vobject
from moto import mock_aws

from iracing_calendar import feed
from iracing_calendar.reconcile import reconcile
from iracing_calendar.sources import Fetcher
from iracing_calendar.store import Conflict, Store
from iracing_calendar.sync import health, refresh

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
SCOPE = "api-season:42"
EVENTS = [
    {
        "id": f"api:1:42:{week}:open|{slot}",
        "round_id": f"api:1:42:{week}:open",
        "coverage": SCOPE,
        "name": "Example sponsored series",
        "start": start,
        "end": None,
        "all_day": False,
        "track": "Road Atlanta",
        "sources": ["https://www.iracing.com/"],
    }
    for week, starts in enumerate(
        [
            [
                "2026-09-26T04:00:00+00:00",
                "2026-09-26T15:00:00+00:00",
                "2026-09-27T00:00:00+00:00",
                "2026-09-27T20:00:00+00:00",
            ],
            [
                "2026-10-10T04:00:00+00:00",
                "2026-10-10T15:00:00+00:00",
                "2026-10-11T00:00:00+00:00",
                "2026-10-11T20:00:00+00:00",
            ],
        ]
    )
    for slot, start in enumerate(starts)
]


def snapshot(events=None, old=None, now=NOW):
    return reconcile(
        old or {}, copy.deepcopy(EVENTS if events is None else events), [SCOPE], now
    )


def test_revisions_corrections_cancellations_rollover():
    first = snapshot()
    assert snapshot(old=first, now=NOW + timedelta(days=7))["ics"] == first["ics"]
    changed = copy.deepcopy(EVENTS)
    for event in changed[:4]:
        event["track"] = "Road Atlanta - Full Course"
    revised = snapshot(changed, first)
    assert [e["sequence"] for e in revised["events"]] == [1] * 4 + [0] * 4
    assert snapshot(changed[:4], revised)["report"]["removed"] == 4
    assert reconcile(first, [], ["api-season:43"], NOW)["ics"] == first["ics"]


def test_placeholder_replacement_and_independent_ics():
    placeholder = EVENTS[0] | {
        "all_day": True,
        "start": "2026-09-26",
        "end": "2026-09-29",
    }
    initial = snapshot([placeholder])
    event = vobject.readOne(initial["ics"]).vevent
    assert event.dtstart.value == date(2026, 9, 26)
    assert event.dtend.value == date(2026, 9, 29)
    assert event.transp.value == "TRANSPARENT"
    assert "Start times unconfirmed" in event.summary.value
    confirmed = vobject.readOne(snapshot(old=initial)["ics"]).vevent_list[0]
    assert confirmed.uid.value == event.uid.value
    assert confirmed.sequence.value == "1"
    assert not hasattr(confirmed, "dtend") and not hasattr(confirmed, "valarm")
    assert vobject.readOne(reconcile({}, [], [], NOW)["ics"]).name == "VCALENDAR"


def test_retention_and_local_time():
    assert not snapshot(now=NOW + timedelta(days=90))["events"]
    tz = ZoneInfo("America/St_Johns")
    assert datetime(2026, 10, 31, 14, tzinfo=UTC).astimezone(tz).hour == 11
    assert datetime(2026, 11, 1, 14, tzinfo=UTC).astimezone(tz).hour == 10
    assert (
        datetime.fromisoformat(EVENTS[2]["start"]).astimezone(tz).isoformat()
        == "2026-09-26T21:30:00-02:30"
    )


def test_adding_and_removing_slots_preserves_other_uids():
    first = snapshot()
    extra = EVENTS[0] | {"start": "2026-09-26T03:00:00+00:00"}
    added = snapshot([extra, *EVENTS], first)
    old_ids = {e["start"]: e["id"] for e in first["events"]}
    assert all(
        e["id"] == old_ids[e["start"]] for e in added["events"] if e["start"] in old_ids
    )
    assert {e["start"]: e["id"] for e in snapshot(old=added)["events"]} == old_ids


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
        return copy.deepcopy(EVENTS), [SCOPE], {}

    result = refresh(store, NOW, extractor)
    assert result["timed"] == 8 and result["status"] == "ok"
    store.claim()
    assert refresh(store, NOW, extractor) == {"status": "busy"}


def test_partial_refresh_publishes_and_logs_identity_warnings(store, caplog):
    special = EVENTS[0] | {
        "id": "special:2026:reviewed-event|0",
        "round_id": "special:2026:reviewed-event",
        "coverage": "special:2026:reviewed-event",
        "provenance": {"special_id": "2026:reviewed-event"},
    }
    previous = reconcile({}, [special], [special["coverage"]], NOW)
    store.write(previous)
    warning = {
        "id": None,
        "status": "unknown",
        "label": "New Sponsor",
        "sources": [],
        "evidence": [],
    }

    def extractor(*args):
        return copy.deepcopy(EVENTS), [SCOPE], {"identity_warnings": [warning]}

    result = refresh(store, NOW + timedelta(hours=6), extractor)
    assert result["status"] == "ok"
    assert result["retained_unverified_ids"] == [special["id"]]
    published = store.read()[0]
    assert published["last_success"] == (NOW + timedelta(hours=6)).timestamp()
    assert (
        next(e for e in published["events"] if e["id"] == special["id"])
        == previous["events"][0]
    )
    assert published["report"]["sources"]["identity_warnings"] == [warning]
    assert "iRacing identity review" in caplog.text
    assert "iRacing retained unverified events" in caplog.text


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
        fetch.get("https://www.iracing.com/")


def test_source_cache_validators(monkeypatch):
    import base64
    from urllib.error import HTTPError

    from iracing_calendar import sources

    url = "https://www.iracing.com/"
    cached = {"body": base64.b64encode(b"literal data").decode(), "etag": '"abc"'}
    fetch = Fetcher({url: cached})

    def unchanged(request, timeout):
        assert request.get_header("If-none-match") == '"abc"'
        raise HTTPError(url, 304, "Not modified", {}, None)

    monkeypatch.setattr(sources, "urlopen", unchanged)
    assert fetch.get(url) == b"literal data"
    assert fetch.used[url] == cached
