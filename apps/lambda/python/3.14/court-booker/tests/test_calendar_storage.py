import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import boto3
import pytest
from booker import calendar_writer
from booker.calendar_contract import normalize_reservation
from booker.calendar_reconcile import reconcile
from booker.calendar_repository import CalendarRepository, LeaseLost
from moto import mock_aws

NOW = datetime(2026, 9, 23, 12, tzinfo=UTC)


def event(id="1", **kwargs):
    return normalize_reservation(
        reservation_id=id,
        equipment_id=1,
        start="2026-09-24T12:00:00Z",
        end="2026-09-24T13:00:00Z",
        court="Court 1",
        **kwargs,
    )


def make_repo(endpoint=None):
    db = boto3.resource(
        "dynamodb",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        **({"endpoint_url": endpoint} if endpoint else {}),
    )
    table = db.create_table(
        TableName="calendar-test-" + uuid.uuid4().hex,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": k, "AttributeType": "S"} for k in ("PK", "SK")
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return CalendarRepository(table)


@pytest.fixture
def repo():
    with mock_aws():
        yield make_repo()


def check_repository(repo):
    repo.put_reservation(event(), now=NOW)
    original = repo.snapshot()["1"]
    repo.put_reservation(event(), now=NOW + timedelta(seconds=1))
    repeated = repo.snapshot()["1"]
    assert original["sequence"] == repeated["sequence"] == 0
    assert original["updated_at"] == repeated["updated_at"]
    assert original["version"] != repeated["version"]
    lease = repo.claim_refresh(now=NOW)
    assert lease
    assert repo.claim_refresh(now=NOW) is None
    assert not repo.put_reservation(
        event(status="cancelled"),
        lease_id=lease,
        expected_version=original["version"],
        now=NOW,
    )
    assert repo.snapshot()["1"]["status"] == "confirmed"
    assert repo.put_reservation(
        event(status="cancelled"),
        lease_id=lease,
        expected_version=repeated["version"],
        now=NOW,
    )
    assert repo.list_events(now=NOW) == []
    assert repo.snapshot()["1"]["sequence"] == 1
    repo.finish_refresh(lease, now=NOW)
    assert repo.get_metadata()["initialized"]
    assert repo.claim_refresh(now=NOW + timedelta(seconds=899)) is None
    assert repo.claim_refresh(now=NOW + timedelta(seconds=900))


def test_repository_contract(repo):
    check_repository(repo)


def test_lease_fences_abandoned_workers(repo):
    old = repo.claim_refresh(now=NOW)
    new = repo.claim_refresh(now=NOW + timedelta(seconds=241))
    assert new != old
    assert not repo.release_refresh(old)
    with pytest.raises(LeaseLost):
        repo.put_reservation(event(), lease_id=old, now=NOW + timedelta(seconds=241))
    with pytest.raises(LeaseLost):
        repo.finish_refresh(old, now=NOW + timedelta(seconds=241))
    assert not repo.snapshot()
    assert repo.get_metadata()["lease_id"] == new


def row(id=1, equipment_id=1, **extra):
    return SimpleNamespace(
        id=id,
        equipment_id=equipment_id,
        class_id=None,
        start_time="2026-09-24 09:30:00",
        end_time="2026-09-24 10:30:00",
        cancelled=False,
        **extra,
    )


def sync(repo, rows, before_return=None):
    def reservations(*_):
        if before_return:
            before_return()
        return rows

    session = SimpleNamespace(login=lambda *_: None, reservations=reservations)
    config = SimpleNamespace(
        timezone="America/St_Johns",
        equipment_ids={"court": 1},
        activity_label=lambda _: "Court 1",
        visibility_for=lambda *_: ("public", None),
    )
    return reconcile(
        repo,
        session,
        config,
        SimpleNamespace(username="x", password="y"),
        repo.claim_refresh(now=NOW, force=True),
        now=NOW,
    )


def test_import_cancel_exclude_and_empty_initialization(repo):
    sync(repo, [row(), row(2, 900)])
    assert set(repo.snapshot()) == {"1"}
    assert len(repo.list_events(now=NOW)) == 1
    sync(repo, [])
    assert repo.list_events(now=NOW) == []
    assert repo.snapshot()["1"]["status"] == "cancelled"
    assert repo.get_metadata()["initialized"]


def test_invalid_later_row_causes_no_mutations(repo):
    repo.put_reservation(event())
    original = repo.snapshot()
    invalid = row(2)
    invalid.end_time = "malformed"
    with pytest.raises(ValueError):
        sync(repo, [row(), invalid])
    assert repo.snapshot() == original
    assert not repo.get_metadata().get("initialized")


def test_new_booking_during_network_response_wins(repo):
    repo.put_reservation(event(), now=NOW)
    sync(repo, [], before_return=lambda: repo.put_reservation(event(), now=NOW))
    assert repo.snapshot()["1"]["status"] == "confirmed"


def test_writer_skips_failed_and_dry_run(monkeypatch, repo):
    monkeypatch.setattr(calendar_writer, "CalendarRepository", lambda: repo)
    for status in ("full", "dry_run", "auth_fail"):
        assert (
            calendar_writer.lambda_handler({"status": status}, None)["status"]
            == "skipped"
        )
    assert (
        calendar_writer.lambda_handler(
            {"status": "already_held", "dry_run": True}, None
        )["status"]
        == "skipped"
    )
    for status in ("booked", "already_held"):
        calendar_writer.lambda_handler(
            {"status": status, "calendar_reservation": event()}, None
        )
    assert len(repo.snapshot()) == 1
    assert repo.snapshot()["1"]["sequence"] == 0


def test_retention(repo):
    repo.put_reservation(event())
    assert repo.list_events(now=datetime(2026, 10, 24, 13, tzinfo=UTC))
    assert not repo.list_events(now=datetime(2026, 10, 24, 13, 0, 1, tzinfo=UTC))


@pytest.mark.skipif(
    not os.environ.get("CALENDAR_LOCALSTACK_ENDPOINT"),
    reason="isolated LocalStack opt-in",
)
def test_localstack_repository():
    repo = make_repo(os.environ["CALENDAR_LOCALSTACK_ENDPOINT"])
    try:
        check_repository(repo)
    finally:
        repo.table.delete()


def test_explicit_cancel_and_successful_empty(repo):
    sync(repo, [])
    assert repo.get_metadata()["initialized"]
    assert repo.list_events(now=NOW) == []
    cancelled = row()
    cancelled.cancelled = True
    sync(repo, [cancelled])
    assert repo.snapshot()["1"]["status"] == "cancelled"
    assert not repo.list_events(now=NOW)


def test_new_record_created_during_refresh_wins(repo):
    def booking_write():
        reservation = event()
        reservation["end"] = "2026-09-24T14:00:00+00:00"
        repo.put_reservation(reservation, now=NOW)

    sync(repo, [row()], before_return=booking_write)
    assert repo.snapshot()["1"]["end"] == "2026-09-24T14:00:00+00:00"


@pytest.mark.parametrize("failure_stage", ["login", "reservations"])
def test_upstream_errors_preserve_previous_calendar(repo, failure_stage):
    repo.put_reservation(event(), now=NOW)
    original = repo.snapshot()

    def fail(*_):
        raise RuntimeError("private upstream payload")

    session = SimpleNamespace(login=lambda *_: None, reservations=lambda *_: [])
    setattr(session, failure_stage, fail)
    config = SimpleNamespace(
        timezone="America/St_Johns",
        equipment_ids={"court": 1},
        activity_label=lambda _: "Court 1",
        visibility_for=lambda *_: ("public", None),
    )
    with pytest.raises(RuntimeError):
        reconcile(
            repo,
            session,
            config,
            SimpleNamespace(username="x", password="y"),
            repo.claim_refresh(now=NOW),
            now=NOW,
        )
    assert repo.snapshot() == original
    assert not repo.get_metadata().get("initialized")


@pytest.mark.skipif(
    not os.environ.get("CALENDAR_LOCALSTACK_ENDPOINT"),
    reason="concurrent conditional writes require isolated LocalStack, not Moto",
)
def test_concurrent_claims_coalesce():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    endpoint = os.environ["CALENDAR_LOCALSTACK_ENDPOINT"]
    repo = make_repo(endpoint)
    try:
        for _ in range(5):
            gate = Barrier(6)

            def claim(_, gate=gate):
                # Separate sessions/resources model independent Lambda requests.
                # Moto's in-process backend does not support concurrent writes.
                table = (
                    boto3.Session()
                    .resource(
                        "dynamodb",
                        region_name="us-east-1",
                        endpoint_url=endpoint,
                        aws_access_key_id="test",
                        aws_secret_access_key="test",
                    )
                    .Table(repo.table.name)
                )
                contender = CalendarRepository(table)
                gate.wait(timeout=30)
                return contender.claim_refresh(now=NOW)

            with ThreadPoolExecutor(max_workers=6) as pool:
                winners = [lease for lease in pool.map(claim, range(6)) if lease]
            assert len(winners) == 1
            assert repo.release_refresh(winners[0])
    finally:
        repo.table.delete()


def test_writer_rejects_status_mismatch(monkeypatch, repo):
    monkeypatch.setattr(calendar_writer, "CalendarRepository", lambda: repo)
    with pytest.raises(ValueError, match="contradicts"):
        calendar_writer.lambda_handler(
            {"status": "cancelled", "calendar_reservation": event()}, None
        )
    assert not repo.snapshot()
