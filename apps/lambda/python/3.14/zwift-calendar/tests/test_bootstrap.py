"""Exercise durable bootstrap admission, replay, cooldowns, and unknown history."""

import copy
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import boto3
import pytest
from moto import mock_aws

from zwift_calendar import backfill, bootstrap
from zwift_calendar.errors import RateLimited
from zwift_calendar.storage import Store

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
ROW = {
    "id": "1-10",
    "parent_id": 2,
    "start": (NOW + timedelta(days=7)).isoformat(),
    "signature": [1, 10000, 0, "RACE"],
    "turnout_division": ["score", "0-200"],
}
TARGET = {"updated": NOW.timestamp(), "turnout": [ROW], "signatures": {}, "score": 100}


@pytest.fixture
def setup(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket="bootstrap-test")
        store = Store("bootstrap-test", s3, clock=lambda: NOW.timestamp())
        store.write("current.json", {"calendars": {"original": True}}, None)
        store.write(backfill.TARGETS, TARGET, None)
        http = Mock(remaining=120)
        auth = Mock()
        monkeypatch.setattr(bootstrap, "Auth", auth)
        populate = Mock()
        monkeypatch.setattr(bootstrap.turnout, "populate", populate)
        yield store, http, populate, auth


def test_snapshot_frozen_and_reservation_survives_crash(setup):
    store, http, populate, _auth = setup
    populate.side_effect = RuntimeError("interrupted")
    with pytest.raises(RuntimeError):
        bootstrap.refresh(store, None, http, NOW, "run1")
    state, _ = store.read(backfill.STATE)
    assert state["bootstrap"]["batches"] == 1
    assert "budget" not in state  # separate explicit allowance
    target, etag = store.read(backfill.TARGETS)
    target["turnout"] = []
    store.write(backfill.TARGETS, target, etag)
    populate.side_effect = None
    result = bootstrap.refresh(store, None, http, NOW, "run1")
    assert result["batches"] == 2
    assert result["turnout"]["target_events"] == 1
    assert store.read()[0] == {"calendars": {"original": True}}


def test_duplicate_execution_cannot_consume_second_allowance(setup):
    store, http, _populate, auth = setup
    bootstrap.refresh(store, None, http, NOW, "run1")
    auth.reset_mock()
    assert bootstrap.refresh(store, None, http, NOW, "run2") == {"status": "conflict"}
    auth.assert_not_called()


def test_budget_and_deadline_stop_without_upstream_calls(setup):
    store, http, _populate, auth = setup
    bootstrap.refresh(store, None, http, NOW, "run1")
    state, etag = store.read(backfill.STATE)
    state["bootstrap"]["batches"] = 100
    store.write(backfill.STATE, state, etag)
    auth.reset_mock()
    result = bootstrap.refresh(store, None, http, NOW, "run1")
    assert result["status"] == "limited"
    assert result["reserved_requests"] == 12000
    auth.assert_not_called()
    # Replays are terminal, not a fresh allowance.
    assert bootstrap.refresh(store, None, http, NOW, "run1")["status"] == "limited"


def test_rate_limit_is_persisted_and_wait_does_not_reserve(setup):
    store, http, populate, auth = setup
    populate.side_effect = RateLimited(900)
    bootstrap.refresh(store, None, http, NOW, "run1")
    auth.reset_mock()
    result = bootstrap.refresh(store, None, http, NOW, "run1")
    assert result["status"] == "running" and result["wait_seconds"] == 900
    assert store.read(backfill.STATE)[0]["bootstrap"]["batches"] == 1
    auth.assert_not_called()


def test_exhausted_history_completes_without_claiming_all_known(setup):
    store, http, _populate, auth = setup
    target = copy.deepcopy(TARGET)
    target["turnout"][0]["parent_id"] = None
    _, etag = store.read(backfill.TARGETS)
    store.write(backfill.TARGETS, target, etag)
    result = bootstrap.refresh(store, None, http, NOW, "run1")
    assert result["status"] == "complete"
    assert result["turnout"]["unknown"] == result["turnout"]["no_parent_link"] == 1
    auth.assert_not_called()


def test_unknown_old_target_schema_fails_without_starting_job(setup):
    store, http, _populate, auth = setup
    _, etag = store.read(backfill.TARGETS)
    store.write(backfill.TARGETS, {"updated": NOW.timestamp()}, etag)
    assert bootstrap.refresh(store, None, http, NOW, "run1") == {"status": "no_targets"}
    assert not store.read(backfill.STATE)[0]
    auth.assert_not_called()


def test_completed_editions_report_filtered_banded_and_unknown_separately():
    cache = {}
    for identity, parent, days, count in [(2, 3, 7, 4), (3, None, 14, 8)]:
        start = (NOW - timedelta(days=days)).isoformat()
        cache[str(identity)] = {
            "parent": parent,
            "start": start,
            "type": "RACE",
            "groups": [
                {
                    "id": identity * 10,
                    "start": start,
                    "division": ROW["turnout_division"],
                    "finishers": count,
                }
            ],
        }
    report = bootstrap.progress({"turnout_events": cache}, TARGET, NOW)
    assert report["filtered"] == report["filtered_banded"] == 1
    assert report["unknown"] == report["pending_editions"] == 0
    assert "turnout" not in ROW


def test_deferred_individual_failures_wait_until_retry_without_spending(setup):
    store, http, _populate, auth = setup
    store.write(
        backfill.STATE,
        {"version": 1, "turnout_retries": {ROW["id"]: NOW.timestamp() + 900}},
        None,
    )
    result = bootstrap.refresh(store, None, http, NOW, "run1")
    assert result["wait_seconds"] == 900
    auth.assert_not_called()


def test_three_stalled_batches_stop_instead_of_looping_forever(setup):
    store, http, populate, _auth = setup
    for _ in range(3):
        bootstrap.refresh(store, None, http, NOW, "run1")
    assert bootstrap.refresh(store, None, http, NOW, "run1")["status"] == "stalled"
    assert populate.call_count == 3


def test_deadline_returns_partial_report_and_keeps_cache(setup):
    store, http, _populate, auth = setup
    bootstrap.refresh(store, None, http, NOW, "run1")
    auth.reset_mock()
    result = bootstrap.refresh(store, None, http, NOW + timedelta(days=1), "run1")
    assert result["status"] == "limited"
    assert result["turnout"]["pending_history"] == 1
    assert store.read(backfill.STATE)[0]["version"] == 1
    auth.assert_not_called()


def test_shared_lease_prevents_spending_or_writing_job(setup):
    store, http, _populate, auth = setup
    store.claim()
    other = Store(store.bucket, store.s3, clock=lambda: NOW.timestamp())
    result = bootstrap.refresh(other, None, http, NOW, "run1")
    assert result["reason"] == "busy"
    assert not store.read(backfill.STATE)[0]
    auth.assert_not_called()


def test_bootstrap_continues_into_duration_history_after_turnout_is_exhausted(
    setup, monkeypatch
):
    store, http, _populate, _auth = setup
    target = copy.deepcopy(TARGET)
    target["turnout"] = []
    sig = ROW["signature"]
    target["signatures"] = {backfill.key(sig): {"signature": sig, "count": 1}}
    _, etag = store.read(backfill.TARGETS)
    store.write(backfill.TARGETS, target, etag)

    def batch(_api, state, _target, _now, _save, **_kwargs):
        # Simulate rollback replacing object references, then a successful unit.
        saved = copy.deepcopy(state)
        state.clear()
        state.update(saved)
        state["races"] = {
            str(i): {
                "start": NOW.isoformat(),
                "samples": [{"signature": sig, "bins": [[100, 1800, 5]]}],
            }
            for i in (1, 2)
        }
        state["successful_units"] = 1
        http.remaining = 100

    monkeypatch.setattr(backfill, "run_batch", batch)
    result = bootstrap.refresh(store, None, http, NOW, "run1")
    assert result["status"] == "complete"
    assert result["duration"]["covered_signatures"] == 1
    job = store.read(backfill.STATE)[0]["bootstrap"]
    assert job["status"] == "complete" and job["requests"] == 20


@pytest.mark.parametrize(
    "discovery_version,expected", [(None, "running"), (1, "complete")]
)
def test_named_series_requires_completed_sibling_discovery(
    setup, monkeypatch, discovery_version, expected
):
    store, http, _populate, _auth = setup
    target = copy.deepcopy(TARGET)
    target["turnout"][0].update(name="Weekly Race", parent_id=None)
    _, etag = store.read(backfill.TARGETS)
    store.write(backfill.TARGETS, target, etag)
    state = {
        "version": 1,
        "scan": {"complete": True, "turnout_discovery_version": discovery_version},
    }
    store.write(backfill.STATE, state, None)
    monkeypatch.setattr(backfill, "run_batch", Mock())
    result = bootstrap.refresh(store, None, http, NOW, "run1")
    assert result["status"] == expected
