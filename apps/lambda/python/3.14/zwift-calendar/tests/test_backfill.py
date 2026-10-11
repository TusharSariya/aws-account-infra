import copy
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import boto3
import httpx
import pytest
from moto import mock_aws

from zwift_calendar import backfill
from zwift_calendar.api import Zwift
from zwift_calendar.duration import estimate
from zwift_calendar.errors import (
    BudgetExceeded,
    ContractError,
    CursorRejected,
    RateLimited,
)
from zwift_calendar.storage import Parameters, Store
from zwift_calendar.transport import API, Transport

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
SIG = [1, 10000, 0, "RACE"]
TARGET = {
    "version": 1,
    "score": 100,
    "updated": NOW.timestamp(),
    "signatures": {
        backfill.key(SIG): {
            "signature": SIG,
            "count": 20,
            "start": (NOW + timedelta(days=1)).isoformat(),
        }
    },
    "events": {},
}


def event(identity=1, parent=None):
    return {
        "id": identity,
        "parentId": parent,
        "eventStart": (NOW - timedelta(days=1)).isoformat(),
        "eventType": "RACE",
        "sport": "CYCLING",
        "eventSubgroups": [
            {
                "id": identity * 10,
                "routeId": 1,
                "distanceInMeters": 10000,
                "laps": 0,
                "rangeAccessLabel": "0-200",
            }
        ],
    }


def results(group):
    return [
        {
            "profileId": i,
            "eventSubgroupId": group,
            "qualified": True,
            "rank": i + 1,
            "scoreHistory": {"previousScore": 100},
            "activityData": {"durationInMilliseconds": (1800 + i * 60) * 1000},
        }
        for i in range(5)
    ]


def test_admission_reserves_slots_and_limits_manual_runs():
    state = {}
    assert backfill.admit(state, NOW)
    assert not backfill.admit(state, NOW + timedelta(minutes=1))
    assert backfill.admit(state, NOW + timedelta(hours=3))
    state["budget"]["daily_runs"] = 8
    assert not backfill.admit(state, NOW + timedelta(hours=6))
    state["budget"]["monthly_runs"] = 248
    assert not backfill.admit(state, NOW + timedelta(days=1))
    assert backfill.admit(state, datetime(2026, 11, 1, tzinfo=UTC))


def test_discovery_cursor_only_finishes_at_terminal_and_queues_matching_events():
    state = backfill.seed({}, TARGET, NOW)
    api = Mock()
    api.history_page.side_effect = [([event()], "next"), ([event()], None)]
    backfill.scan_page(api, state, TARGET, NOW)
    assert state["scan"]["cursor"] == "next"
    backfill.scan_page(api, state, TARGET, NOW)
    assert len(state["pending"]) == 1
    assert state["scan"]["phase"] == 1
    assert api.history_page.call_args.args[1] == "next"
    assert not state["scan"].get("complete")


def test_expired_cursor_defers_without_claiming_completion():
    state = backfill.seed({}, TARGET, NOW)
    state["scan"] = {"anchor": NOW.isoformat(), "phase": 0, "cursor": "expired"}
    api = Mock()
    api.history_page.side_effect = CursorRejected()
    assert not backfill.scan_page(api, state, TARGET, NOW)
    assert "cursor" not in state["scan"]
    assert state["scan"]["retry_after"] == NOW.timestamp() + 86400


def test_parent_cycle_and_repeated_results_do_not_inflate_evidence():
    state = backfill.seed({}, TARGET, NOW)
    backfill.enqueue(state, "1", {"start": None})
    api = Mock()
    api.event.side_effect = [event(1, 2), event(2, 1)]
    api.results.side_effect = [results(10), results(20)]
    backfill.sample_event(api, state, "1", TARGET, NOW)
    assert "2" in state["pending"]
    backfill.sample_event(api, state, "2", TARGET, NOW)
    assert not state["pending"]
    backfill.enqueue(state, "1", {"start": None})
    assert not state["pending"]
    result = estimate({"signature": SIG, "published_seconds": 0}, state, 100)
    assert result["samples"] == 10 and result["seconds"] == 1920
    assert "profileId" not in json.dumps(state)


def test_empty_results_retried_once_after_a_day():
    state = backfill.seed({}, TARGET, NOW)
    backfill.enqueue(state, "1", {"start": None})
    api = Mock()
    recent = event()
    recent["eventStart"] = (NOW - timedelta(hours=4)).isoformat()
    api.event.return_value = recent
    api.results.return_value = []
    backfill.sample_event(api, state, "1", TARGET, NOW)
    assert state["pending"]["1"]["retry_after"] == NOW.timestamp() + 86400
    backfill.sample_event(api, state, "1", TARGET, NOW + timedelta(days=1))
    assert not state["pending"] and state["races"]["1"]["samples"][0]["bins"] == []


def test_target_change_revisits_previously_irrelevant_metadata():
    state = backfill.seed({}, TARGET, NOW)
    state["races"]["1"] = {
        "scope": state["scope"],
        "start": NOW.isoformat(),
        "samples": [],
    }
    updated = copy.deepcopy(TARGET)
    updated["score"] = 200
    backfill.seed(state, updated, NOW)
    backfill.enqueue(state, "1", {"start": None})
    assert "1" in state["pending"]


def test_size_limit_evicts_unused_history_but_protects_current_evidence(monkeypatch):
    monkeypatch.setattr(backfill, "MAX_BYTES", 300)
    race = {
        "start": NOW.isoformat(),
        "samples": [{"signature": SIG, "bins": [[100, 100, 1]]}],
        "padding": "x" * 500,
    }
    state = {"races": {"1": race}}
    with pytest.raises(BudgetExceeded):
        backfill.bounded(copy.deepcopy(state), TARGET)
    assert backfill.bounded(state, {"signatures": {}})["races"] == {}


def test_backfill_rate_limit_does_not_sleep_or_retry_and_all_attempts_are_bounded():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "600"})

    http = Transport(
        httpx.Client(transport=httpx.MockTransport(handle)),
        defer_rate_limits=True,
        sleep=lambda _: None,
        budget=120,
    )
    with pytest.raises(RateLimited) as exc:
        http.request(API + "event-feed?from=1")
    assert exc.value.seconds == 600 and len(calls) == 1 and http.remaining == 119


def test_history_page_rejects_repeated_cursors_and_non_json_contract():
    http = Mock()
    http.request.return_value = {"data": [{"event": event()}], "cursor": "same"}
    with pytest.raises(ContractError):
        Zwift(http, "token").history_page(NOW, "same")


def test_batch_rate_limit_persists_cooldown_and_preserves_history():
    state = backfill.seed({}, TARGET, NOW)
    api = Mock()
    api.http.remaining = 120
    api.http.clock.return_value = 0
    api.http.deadline = 150
    api.history_page.side_effect = RateLimited(900)
    backfill.run_batch(api, state, TARGET, NOW, Mock())
    assert state["retry_after"] == NOW.timestamp() + 900
    assert state["races"] == {}


def test_batch_request_budget_and_checkpoints_are_bounded():
    state = backfill.seed({}, TARGET, NOW)
    api = Mock()
    api.http.remaining = 120
    api.http.clock.return_value = 0
    api.http.deadline = 150

    def page(*args):
        api.http.remaining -= 1
        return [], str(api.http.remaining)

    api.history_page.side_effect = page
    save = Mock()
    backfill.run_batch(api, state, TARGET, NOW, save)
    assert api.history_page.call_count == 120
    assert save.call_count <= 3


@mock_aws
def test_worker_imports_legacy_and_never_publishes_calendar(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    s3 = boto3.client("s3")
    s3.create_bucket(Bucket="history-test")
    store = Store("history-test", s3, clock=lambda: NOW.timestamp())
    original = {"calendars": {"banded": {"ics": "unchanged"}}, "last_success": 123}
    store.write("current.json", original, None)
    store.write("private.json", {"history": {"races": {}, "pending": {}}}, None)
    store.write(backfill.TARGETS, TARGET | {"signatures": {}}, None)
    http = Mock()
    http.remaining = 120
    result = backfill.refresh_history(store, Parameters(), http, NOW)
    assert result["status"] == "ok"
    assert store.read()[0] == original
    assert store.read(backfill.STATE)[0]["budget"]["monthly_runs"] == 1
    result = backfill.refresh_history(store, Parameters(), http, NOW)
    assert result["status"] == "budget_limited"
    http.request.assert_not_called()


@mock_aws
def test_worker_busy_preserves_snapshot_and_spends_no_upstream_requests(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    s3 = boto3.client("s3")
    s3.create_bucket(Bucket="history-test")
    store = Store("history-test", s3, clock=lambda: NOW.timestamp())
    store.claim()
    other = Store("history-test", s3, clock=lambda: NOW.timestamp())
    http = Mock()
    assert backfill.refresh_history(other, Parameters(), http, NOW) == {
        "status": "busy"
    }
    http.request.assert_not_called()


def test_hourly_sync_enriches_from_cache_without_fetching_history():
    from pathlib import Path

    from icalendar import Calendar

    from zwift_calendar.api import instant
    from zwift_calendar.service import collect

    race = json.loads((Path(__file__).parent / "fixtures/race.json").read_text())
    race["name"] = "Synthetic eligible race"
    now = instant(race["eventStart"]) - timedelta(minutes=1)
    profile = {
        "current": 100,
        "max30": 100,
        "retrieved_at": now.timestamp(),
        "fields": {"profile.playerType": "NORMAL", "profile.male": True},
    }
    api = Mock()
    api.profile.return_value = profile
    api.upcoming.return_value = [race]
    first, private, _ = collect(api, {}, now)
    row = next(iter(private["revisions"].values()))
    history = {
        "races": {
            str(i): {
                "start": (now - timedelta(days=1)).isoformat(),
                "samples": [{"signature": row["signature"], "bins": [[100, 2400, 5]]}],
            }
            for i in (1, 2)
        }
    }
    second, _, report = collect(
        api, private | {"history": history}, now + timedelta(seconds=1)
    )
    old = Calendar.from_ical(first["calendars"]["banded"]["ics"]).walk("VEVENT")[0]
    new = Calendar.from_ical(second["calendars"]["banded"]["ics"]).walk("VEVENT")[0]
    assert old["UID"] == new["UID"]
    assert new["SEQUENCE"] == old["SEQUENCE"] + 1
    assert new.decoded("DTEND") - new.decoded("DTSTART") == timedelta(minutes=40)
    assert report["history_requests"] == 0
    api.event.assert_not_called()
    api.results.assert_not_called()


def test_resume_after_checkpoint_does_not_repeat_discovery_pages():
    state = backfill.seed({}, TARGET, NOW)
    api = Mock()
    api.http.remaining = 120
    api.http.clock.return_value = 0
    api.http.deadline = 150
    saved = []

    def page(since, cursor):
        api.http.remaining -= 1
        return [], str(int(cursor or "0") + 1)

    api.history_page.side_effect = page

    def checkpoint(value):
        saved.append(copy.deepcopy(value))
        raise RuntimeError("simulated termination after durable write")

    with pytest.raises(RuntimeError):
        backfill.run_batch(api, state, TARGET, NOW, checkpoint)
    assert saved[0]["scan"]["cursor"] == "30"
    api.http.remaining = 120
    backfill.run_batch(api, saved[0], TARGET, NOW, Mock())
    assert saved[0]["scan"]["cursor"] == "150"


@pytest.mark.parametrize("change", ["signature", "score"])
def test_discovery_advances_across_hourly_target_changes(change):
    state = backfill.seed({}, TARGET, NOW)
    api = Mock()
    api.http.clock.return_value = 0
    api.http.deadline = 150
    cursors = []

    def page(since, cursor):
        api.http.remaining -= 1
        cursors.append(cursor)
        number = int(cursor or "0") + 1
        return [], str(number) if number < 3 else None

    api.history_page.side_effect = page
    for hour in range(3):
        target = copy.deepcopy(TARGET)
        if change == "score":
            target["score"] += hour
        else:
            sig = [hour + 2, 10000, 0, "RACE"]
            target["signatures"][backfill.key(sig)] = {
                "signature": sig,
                "count": 1,
                "start": NOW.isoformat(),
            }
        backfill.seed(state, target, NOW + timedelta(hours=hour))
        api.http.remaining = 1
        backfill.run_batch(api, state, target, NOW + timedelta(hours=hour), Mock())

    assert cursors == [None, "1", "2"]
    assert state["scan"]["phase"] == 1
    assert state["scan"]["anchor"] == NOW.isoformat()


def test_seed_expires_history_and_pending_older_than_ninety_days():
    old = (NOW - timedelta(days=91)).isoformat()
    state = {
        "races": {"1": {"start": old, "samples": []}},
        "pending": {"2": {"start": old}},
    }
    backfill.seed(state, TARGET, NOW)
    assert not state["races"] and not state["pending"]


def test_enabled_history_health_alerts_only_for_stale_uncovered_targets(monkeypatch):
    from zwift_calendar.service import serve

    monkeypatch.setenv("HISTORY_ENABLED", "true")
    snapshot = {
        "last_success": NOW.timestamp(),
        "calendars": {k: {"ics": "data", "etag": k} for k in ("banded", "unbanded")},
    }
    state = {"last_success": NOW.timestamp() - 86401}
    store = Mock()
    store.read.side_effect = lambda path="current.json": (
        {"current.json": snapshot, backfill.STATE: state, backfill.TARGETS: TARGET}[
            path
        ],
        None,
    )
    with pytest.raises(RuntimeError, match="Historical backfill"):
        serve({"health": True}, store, NOW)
    state["last_success"] = NOW.timestamp()
    assert serve({"health": True}, store, NOW) == {"status": "ok"}


def test_detail_float_distance_matches_integer_feed_signature():
    sig = [1, 0, 1, "RACE"]
    target = TARGET | {
        "signatures": {backfill.key(sig): {"signature": sig, "count": 1}}
    }
    state = backfill.seed({}, target, NOW)
    backfill.enqueue(state, "1", {"start": None})
    detail = event()
    detail["eventSubgroups"][0].update(distanceInMeters=0.0, laps=1)
    api = Mock()
    api.event.return_value = detail
    api.results.return_value = results(10)
    backfill.sample_event(api, state, "1", target, NOW)
    assert state["races"]["1"]["samples"]
    assert sum(b[2] for b in state["races"]["1"]["samples"][0]["bins"]) == 5


def test_seed_migrates_frozen_float_keys_without_losing_event_counts():
    sig = [1, 0, 1, "RACE"]
    target = {
        "score": 100,
        "signatures": {
            '[1,0,1,"RACE"]': {"signature": sig, "count": 2},
            '[1,0.0,1,"RACE"]': {"signature": [1, 0.0, 1, "RACE"], "count": 3},
        },
    }
    backfill.seed({}, target, NOW)
    assert list(target["signatures"]) == [backfill.key(sig)]
    assert target["signatures"][backfill.key(sig)]["count"] == 5
    backfill.seed({}, target, NOW)
    assert target["signatures"][backfill.key(sig)]["count"] == 5
    assert backfill.key([1, 0.5, 1, "RACE"]) != backfill.key(sig)


def test_mature_complete_empty_results_do_not_delay_full_backfill_a_day():
    state = backfill.seed({}, TARGET, NOW)
    backfill.enqueue(state, "1", {"start": None})
    api = Mock()
    old = event()
    old["eventStart"] = (NOW - timedelta(days=7)).isoformat()
    api.event.return_value = old
    api.results.return_value = []
    backfill.sample_event(api, state, "1", TARGET, NOW)
    assert "1" not in state["pending"]
    assert state["races"]["1"]["samples"][0]["bins"] == []


def test_seed_releases_only_mature_empty_result_retries():
    state = backfill.seed({}, TARGET, NOW)
    state["pending"] = {
        "1": {
            "start": (NOW - timedelta(days=7)).isoformat(),
            "empty_retries": 1,
            "retry_after": NOW.timestamp() + 86400,
        },
        "2": {
            "start": (NOW - timedelta(hours=4)).isoformat(),
            "empty_retries": 1,
            "retry_after": NOW.timestamp() + 86400,
        },
        "3": {
            "start": (NOW - timedelta(days=7)).isoformat(),
            "retry_after": NOW.timestamp() + 86400,
        },
    }
    backfill.seed(state, TARGET, NOW)
    assert "retry_after" not in state["pending"]["1"]
    assert "retry_after" in state["pending"]["2"]
    assert "retry_after" in state["pending"]["3"]


def test_full_scan_continues_for_turnout_after_duration_coverage():
    state = backfill.seed({}, TARGET | {"signatures": {}}, NOW)
    api = Mock()
    api.http.remaining = 1
    api.http.clock.return_value = 0
    api.http.deadline = 150

    def page(*_args):
        api.http.remaining -= 1
        return [], None

    api.history_page.side_effect = page
    backfill.run_batch(
        api, state, TARGET | {"signatures": {}}, NOW, Mock(), full_scan=True
    )
    assert api.history_page.call_count == 1
    assert state["scan"]["turnout_discovery_version"] == 1


def test_revisiting_covered_race_preserves_learned_duration():
    state = backfill.seed({}, TARGET, NOW)
    api = Mock()
    api.event.side_effect = lambda identity: event(identity)
    api.results.side_effect = results
    for identity in ("1", "2"):
        backfill.enqueue(state, identity, {"start": None})
        backfill.sample_event(api, state, identity, TARGET, NOW)
    before = copy.deepcopy(state["races"]["1"]["samples"])
    state["pending"]["1"] = {"start": None}
    backfill.sample_event(api, state, "1", TARGET | {"signatures": {}}, NOW)
    assert state["races"]["1"]["samples"] == before
    assert (
        estimate({"signature": SIG, "published_seconds": 0}, state, 100)["samples"]
        == 10
    )


def test_refresh_replaces_its_group_without_erasing_other_groups():
    state = backfill.seed({}, TARGET, NOW)
    unchanged = {
        "subgroup_id": 11,
        "signature": SIG,
        "division": ["score", "200-300"],
        "bins": [[250, 2000, 6]],
    }
    state["races"]["1"] = {
        "start": event()["eventStart"],
        "samples": [
            {"subgroup_id": 10, "signature": SIG, "bins": [[100, 9999, 5]]},
            {"signature": SIG, "bins": [[100, 9999, 5]]},
            unchanged,
        ],
    }
    state["pending"]["1"] = {"start": None}
    api = Mock()
    api.event.return_value = event()
    api.results.return_value = results(10)
    backfill.sample_event(api, state, "1", TARGET, NOW)
    samples = state["races"]["1"]["samples"]
    assert len(samples) == 2 and unchanged in samples
    refreshed = next(s for s in samples if s["subgroup_id"] == 10)
    assert sum(b[2] for b in refreshed["bins"]) == 5
    assert all(b[1] != 9999 for s in samples for b in s["bins"])


def test_missing_metadata_is_unknown_not_an_empty_completed_race():
    from zwift_calendar.errors import EventUnavailable

    state = backfill.seed({}, TARGET, NOW)
    api = Mock()
    api.event.side_effect = EventUnavailable()
    backfill.enqueue(state, "1", {"start": None})
    backfill.sample_event(api, state, "1", TARGET, NOW)
    assert "1" not in state["races"] and "1" not in state["pending"]
    assert backfill.status(state, TARGET)["unavailable_events"] == 1
    backfill.enqueue(state, "1", {"start": None})
    assert not state["pending"]
    backfill.seed(state, TARGET, NOW + timedelta(days=1))
    backfill.enqueue(state, "1", {"start": None})
    assert "1" in state["pending"]


def test_deferred_metadata_is_reclassified_only_once():
    state = {"pending": {"1": {"start": None, "retry_after": NOW.timestamp() + 86400}}}
    backfill.seed(state, TARGET, NOW)
    assert "retry_after" not in state["pending"]["1"]
    state["pending"]["1"]["retry_after"] = NOW.timestamp() + 86400
    backfill.seed(state, TARGET, NOW)
    assert "retry_after" in state["pending"]["1"]


def test_only_metadata_404_is_classified_as_unavailable():
    from zwift_calendar.errors import EventUnavailable, UpstreamError

    http = Transport(
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(404)))
    )
    with pytest.raises(EventUnavailable):
        Zwift(http).event(1)
    with pytest.raises(UpstreamError) as exc:
        Zwift(http, "token").finisher_count(10)
    assert not isinstance(exc.value, EventUnavailable)
