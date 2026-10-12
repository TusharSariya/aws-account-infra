import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import boto3
import httpx
import pytest
from moto import mock_aws

from zwift_calendar.api import Zwift
from zwift_calendar.auth import CREDENTIALS, TOKENS, Auth
from zwift_calendar.errors import (
    AuthenticationError,
    BudgetExceeded,
    ContractError,
    UpstreamError,
)
from zwift_calendar.service import collect, refresh
from zwift_calendar.storage import Busy, Parameters, Store
from zwift_calendar.transport import API, TOKEN_URL, Transport


@pytest.fixture
def storage(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket="zwift-test-snapshot")
        yield (
            Store("zwift-test-snapshot", s3, clock=lambda: 1000),
            Parameters(boto3.client("ssm")),
        )


def test_exclusive_lease_and_expired_owner(storage):
    store, _ = storage
    assert store.claim() == {}
    other = Store(store.bucket, store.s3, clock=lambda: 1000)
    with pytest.raises(Busy):
        other.claim()
    store.publish({"ics": "first"})
    store.release()
    assert store.read()[0] == {"ics": "first"}
    store.claim()
    other.clock = lambda: 2000
    other.claim()
    with pytest.raises(Busy):
        store.publish({"ics": "stale"})
    store.release()
    assert other.read()[0]["ics"] == "first"


def test_tokens_persist_before_use_and_refresh(storage):
    store, parameters = storage
    store.claim()
    parameters.write(CREDENTIALS, {"username": "synthetic", "password": "synthetic"})
    http = Mock()
    http.request.return_value = {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_in": 3600,
        "refresh_expires_in": 8000,
    }
    auth = Auth(http, parameters, store, clock=lambda: 1000)
    assert auth.access() == "access"
    assert parameters.read(TOKENS)["refresh_token"] == "refresh"
    assert auth.access() == "access"
    assert http.request.call_count == 1
    auth.clock = lambda: 5000
    auth.access()
    assert http.request.call_args.kwargs["form"]["grant_type"] == "refresh_token"


def test_uncertain_exchange_leaves_marker(storage):
    store, parameters = storage
    store.claim()
    parameters.write(CREDENTIALS, {"username": "synthetic", "password": "synthetic"})
    http = Mock()
    http.request.side_effect = UpstreamError("timeout")
    with pytest.raises(UpstreamError):
        Auth(http, parameters, store).access()
    assert parameters.read(TOKENS) == {"state": "exchange_pending"}


def test_standard_parameter_size(storage):
    _, parameters = storage
    with pytest.raises(ValueError):
        parameters.write(TOKENS, {"token": "x" * 4096})


def test_transport_redacts_and_never_follows_redirects():
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(
            302, headers={"Location": "https://example.com/secret"}, text="secret body"
        )

    http = Transport(httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(UpstreamError, match="Unexpected Zwift"):
        http.request(API + "scoring/current", token="secret")
    assert count == 1
    with pytest.raises(ContractError):
        http.request("https://example.com/", token="secret")


def test_retry_budget_and_no_auth_retries():
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(503, text="private response")

    http = Transport(
        httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None
    )
    with pytest.raises(UpstreamError):
        http.request(TOKEN_URL, form={"password": "secret"})
    assert len(calls) == 1
    with pytest.raises(UpstreamError):
        http.request(API + "public/events/upcoming")
    assert len(calls) == 4
    http.remaining = 0
    with pytest.raises(BudgetExceeded):
        http.request(API + "public/events/upcoming")


def test_pagination_does_not_stop_at_parent_horizon():
    now = datetime.now(UTC)
    page = [
        {"id": i, "eventStart": (now + timedelta(days=20)).isoformat()}
        for i in range(200)
    ]
    http = Mock()
    http.request.side_effect = [
        {"data": [{"event": e} for e in page], "cursor": "next"},
        {"data": [], "cursor": None},
    ]
    assert len(Zwift(http, "token").upcoming(now + timedelta(days=14))) == 200
    assert "cursor=next" in http.request.call_args.args[0]
    http.request.side_effect = [
        {"data": [{"event": e} for e in page], "cursor": "next"}
    ] * 2
    with pytest.raises(ContractError, match="cursor"):
        Zwift(http, "token").upcoming(now + timedelta(days=14))


def test_score_failure_keeps_cached_score_but_not_forever():
    now = datetime.now(UTC)
    api = Mock()
    api.profile.side_effect = AuthenticationError("unavailable")
    api.upcoming.return_value = []
    profile = {
        "current": 100,
        "max30": 100,
        "fields": {},
        "retrieved_at": now.timestamp() - 3600,
    }
    snapshot, _, report = collect(api, {"profile": profile}, now)
    assert report["score_degraded"] is True
    assert all("VCALENDAR" in feed["ics"] for feed in snapshot["calendars"].values())
    profile["retrieved_at"] -= 86400
    with pytest.raises(AuthenticationError):
        collect(api, {"profile": profile}, now)
    with pytest.raises(AuthenticationError):
        collect(api, {}, now)


def test_refresh_failure_preserves_snapshot(storage, monkeypatch):
    store, parameters = storage
    store.write("current.json", {"ics": "last good"}, None)
    monkeypatch.setattr("zwift_calendar.service.Auth.access", lambda self: "token")
    http = Mock()
    http.request.side_effect = ContractError("invalid response")
    with pytest.raises(ContractError):
        refresh(store, parameters, http, datetime.now(UTC))
    assert store.read()[0] == {"ics": "last good"}


def test_preview_does_not_publish_or_advance_revisions(storage, monkeypatch):
    store, parameters = storage
    store.write("current.json", {"ics": "last good", "etag": "old"}, None)
    monkeypatch.setattr("zwift_calendar.service.Auth.access", lambda self: "token")
    monkeypatch.setattr(
        "zwift_calendar.service.collect",
        lambda *args, **kwargs: (
            {
                "calendars": {
                    key: {"ics": "preview", "etag": "new"}
                    for key in ("banded", "unbanded")
                }
            },
            {"revisions": {"new": {}}},
            {"score_degraded": False},
        ),
    )
    result = refresh(store, parameters, Mock(), datetime.now(UTC), preview=True)
    assert all(feed["ics"] == "preview" for feed in result["calendars"].values())
    assert store.read()[0]["ics"] == "last good"
    assert store.read("private.json")[0]["revisions"] == {}


def test_feed_role_snapshot_contains_no_profile(storage, monkeypatch):
    store, parameters = storage
    monkeypatch.setattr("zwift_calendar.service.Auth.access", lambda self: "token")
    monkeypatch.setattr(
        "zwift_calendar.service.collect",
        lambda *args, **kwargs: (
            {
                "calendars": {
                    key: {"ics": "safe", "etag": "new"}
                    for key in ("banded", "unbanded")
                }
            },
            {"profile": {"private": "account"}},
            {"score_degraded": False},
        ),
    )
    refresh(store, parameters, Mock(), datetime.now(UTC))
    assert "account" not in json.dumps(store.read()[0])
    assert store.read("private.json")[0]["profile"] == {"private": "account"}


def test_cursor_overlap_is_deduplicated_and_partial_failure_aborts():
    now = datetime.now(UTC)
    row = {"id": 1, "eventStart": now.isoformat()}
    http = Mock()
    http.request.side_effect = [
        {"data": [{"event": row}], "cursor": "next"},
        {"data": [{"event": row}, {"event": row | {"id": 2}}], "cursor": None},
    ]
    assert [
        r["id"] for r in Zwift(http, "token").upcoming(now + timedelta(days=14))
    ] == [1, 2]
    http.request.side_effect = [
        {"data": [{"event": row}], "cursor": "next"},
        UpstreamError("timeout"),
    ]
    with pytest.raises(UpstreamError):
        Zwift(http, "token").upcoming(now + timedelta(days=14))


def test_rejected_refresh_can_reauthenticate_but_uncertain_refresh_cannot(storage):
    store, parameters = storage
    store.claim()
    parameters.write(CREDENTIALS, {"username": "synthetic", "password": "synthetic"})
    expired = {"refresh_token": "old", "expires_at": 0, "refresh_expires_at": 9000}
    issued = {
        "access_token": "new",
        "refresh_token": "new-refresh",
        "expires_in": 3600,
        "refresh_expires_in": 8000,
    }
    http = Mock()
    parameters.write(TOKENS, expired)
    http.request.side_effect = [AuthenticationError("rejected"), issued]
    assert Auth(http, parameters, store, clock=lambda: 1000).access() == "new"
    assert [c.kwargs["form"]["grant_type"] for c in http.request.call_args_list] == [
        "refresh_token",
        "password",
    ]
    parameters.write(TOKENS, expired)
    http.reset_mock()
    http.request.side_effect = UpstreamError("timeout")
    with pytest.raises(UpstreamError):
        Auth(http, parameters, store, clock=lambda: 1000).access()
    assert http.request.call_count == 1
    assert parameters.read(TOKENS) == {"state": "exchange_pending"}


def test_history_bootstrap_uses_qualified_anonymous_samples():
    from zwift_calendar.duration import learn

    now = datetime.now(UTC)
    sig = [123, 10000, 0, "RACE"]
    selected = [{"signature": sig, "event_id": 1}]
    events = [
        {"id": 1, "eventStart": (now + timedelta(hours=1)).isoformat(), "parentId": 2}
    ]
    group = {
        "id": 3,
        "rangeAccessLabel": "0-160",
        "routeId": 123,
        "distanceInMeters": 10000,
        "laps": 0,
    }
    api = Mock()
    api.event.return_value = {
        "id": 2,
        "eventType": "RACE",
        "eventStart": (now - timedelta(days=7)).isoformat(),
        "eventSubgroups": [group],
    }
    api.results.return_value = [
        {
            "profileId": 99,
            "eventSubgroupId": 3,
            "qualified": True,
            "rank": 1,
            "scoreHistory": {"previousScore": 100},
            "activityData": {"durationInMilliseconds": 1800000},
            "profileData": {"firstName": "PRIVATE"},
        }
    ]
    history, report = learn(api, events, selected, {}, 100, now)
    assert history["races"]["2"]["samples"][0]["bins"] == [[100, 1800, 1]]
    assert "PRIVATE" not in json.dumps(history) and "profileId" not in json.dumps(
        history
    )
    assert report["history_requests"] == 1
    assert "1" in history["pending"]


def test_missing_current_score_uses_known_maximum_without_provisional_claim():
    now = datetime.now(UTC)
    api = Mock()
    api.profile.return_value = {
        "current": None,
        "max30": 63,
        "fields": {},
        "retrieved_at": now.timestamp(),
    }
    api.upcoming.return_value = []
    _, state, report = collect(api, {}, now)
    assert report["provisional"] is False
    assert state["profile"]["max30"] == 63


def test_second_calendar_render_failure_preserves_both_published_feeds(
    storage, monkeypatch
):
    store, parameters = storage
    previous = {
        "calendars": {
            key: {"ics": key + " old", "etag": key} for key in ("banded", "unbanded")
        },
        "last_success": 1000,
    }
    store.write("current.json", previous, None)
    monkeypatch.setattr("zwift_calendar.service.Auth.access", lambda self: "token")
    api = Mock()
    now = datetime.now(UTC)
    api.profile.return_value = {
        "current": 100,
        "max30": 100,
        "fields": {},
        "retrieved_at": now.timestamp(),
    }
    api.upcoming.return_value = []
    monkeypatch.setattr("zwift_calendar.service.Zwift", lambda *args: api)
    monkeypatch.setattr(
        "zwift_calendar.calendar.render",
        Mock(side_effect=["banded new", ValueError("render failed")]),
    )
    with pytest.raises(ValueError):
        refresh(store, parameters, Mock(), now)
    assert store.read()[0] == previous
    assert store.read("private.json")[0] == {}


def test_activity_checkpoints_survive_later_discovery_failure(storage, monkeypatch):
    from zwift_calendar.activities import STATE as POWER_STATE

    store, parameters = storage
    monkeypatch.setattr("zwift_calendar.service.Auth.access", lambda self: "token")

    def collect_then_fail(api, state, now, *, checkpoint):
        checkpoint(
            {"version": 1, "activities": {}, "scan": {"head": "1", "offset": 50}}
        )
        raise UpstreamError("event feed failed")

    monkeypatch.setattr("zwift_calendar.service.collect", collect_then_fail)
    previous = {"calendars": {"banded": {"ics": "old", "etag": "old"}}}
    store.write("current.json", previous, None)
    with pytest.raises(UpstreamError):
        refresh(store, parameters, Mock(), datetime.now(UTC))
    assert store.read()[0] == previous
    assert store.read(POWER_STATE)[0]["scan"]["offset"] == 50


def test_no_activities_publish_labelled_default_then_use_recording(monkeypatch):
    from pathlib import Path

    from icalendar import Calendar

    from zwift_calendar.api import instant

    race = json.loads((Path(__file__).parent / "fixtures/race.json").read_text())
    race["name"] = "Synthetic eligible race"
    now = instant(race["eventStart"]) - timedelta(minutes=1)
    api = Mock()
    api.profile.return_value = {
        "current": 100,
        "max30": 100,
        "retrieved_at": now.timestamp(),
        "fields": {
            "profile.profileId": 1,
            "profile.male": True,
            "profile.playerType": "NORMAL",
        },
        "body": {"weight_kg": 75, "height_cm": 183},
    }
    api.upcoming.return_value = [race]
    api.activities.return_value = []
    first, state, report = collect(api, {}, now)
    original = Calendar.from_ical(first["calendars"]["banded"]["ics"]).walk("VEVENT")[0]
    assert original["X-ZWIFT-ESTIMATE-SOURCE"] == "default"
    assert "100 W FTP-based default" in original["DESCRIPTION"]
    assert report["power_collection"]["confirmed_no_activities"]
    api.activities.side_effect = [
        [
            {
                "id": 1,
                "sport": "CYCLING",
                "endDate": (now - timedelta(days=1)).isoformat(),
            }
        ],
        [],
    ]
    api.activity_fit.return_value = b"fit"
    monkeypatch.setattr(
        "zwift_calendar.activities.fit_curve", lambda *args: {"60": 200, "3600": 180}
    )
    second, _, report = collect(api, state, now)
    changed = Calendar.from_ical(second["calendars"]["banded"]["ics"]).walk("VEVENT")[0]
    assert changed["UID"] == original["UID"]
    assert changed["SEQUENCE"] == original["SEQUENCE"] + 1
    assert changed["X-ZWIFT-ESTIMATE-SOURCE"] in ("measured", "extrapolated")
    assert not report["power_collection"]["confirmed_no_activities"]
