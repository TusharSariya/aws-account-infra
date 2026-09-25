"""Private (coaching) bookings stay off public calendar links."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from booker import calendar_cli, calendar_writer
from booker.calendar_contract import normalize_reservation
from booker.calendar_feed import serve
from booker.calendar_ics import render_calendar
from booker.calendar_reconcile import reconcile
from booker.config import load_bookings
from booker.handler import run_booking
from booker.http import HeldReservation, UpaceHttpBooker
from booker.results import BOOKED
from booker.secrets import Credentials
from icalendar import Calendar
from moto import mock_aws
from test_calendar_storage import make_repo
from test_http import FakeSession

TZ = ZoneInfo("America/St_Johns")
BOOKINGS = Path(__file__).resolve().parents[5] / "ecr/court-booker/bookings.yaml"
CREDS = Credentials(username="user@example.com", password="stub")
NOW = datetime(2026, 9, 23, 12, tzinfo=UTC)
COURT1 = "3-1 - Squash & Racquetball Court 1"


def _config():
    return load_bookings(BOOKINGS)


@pytest.fixture
def repo():
    with mock_aws():
        yield make_repo()


# --- bookings.yaml ---------------------------------------------------------


def test_coaching_rules_are_private_and_disabled():
    coaching = [rule for rule in _config().weekly if rule.visibility == "private"]
    assert [(r.activity, r.weekday, r.time) for r in coaching] == [
        ("court1", "Wed", "09:00"),
        ("court1", "Fri", "09:00"),
    ]
    assert all(r.title == "Coaching" and not r.enabled for r in coaching)
    assert all(r.duration_min == 60 and r.people == 1 for r in coaching)
    public = [rule for rule in _config().weekly if rule.visibility == "public"]
    assert public and all(rule.title is None for rule in public)


@pytest.mark.parametrize(
    ("activity", "local_start", "expected"),
    [
        ("court1", datetime(2026, 9, 30, 9, 0), ("private", "Coaching")),
        ("court1", datetime(2026, 10, 2, 9, 0), ("private", "Coaching")),
        ("court1", datetime(2026, 10, 2, 9, 0, tzinfo=TZ), ("private", "Coaching")),
        ("court1", datetime(2026, 9, 30, 9, 30), ("public", None)),
        ("court1", datetime(2026, 9, 30, 10, 0), ("public", None)),
        ("court1", datetime(2026, 10, 1, 9, 0), ("public", None)),
        ("court2", datetime(2026, 9, 30, 9, 0), ("public", None)),
        ("court1", datetime(2026, 9, 28, 17, 0), ("public", None)),
    ],
)
def test_visibility_for_matches_disabled_private_rules(activity, local_start, expected):
    # Both coaching rules ship disabled; they still classify their slots.
    assert _config().visibility_for(activity, local_start) == expected


def test_rule_visibility_is_validated(tmp_path):
    text = BOOKINGS.read_text(encoding="utf-8").replace(
        "    visibility: private", "    visibility: secret", 1
    )
    path = tmp_path / "bookings.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="public or private"):
        load_bookings(path)


# --- booking ---------------------------------------------------------------


def _book(event, now=None):
    browser = UpaceHttpBooker(session_factory=FakeSession)
    return run_booking(event, config=_config(), creds=CREDS, browser=browser, now=now)


def test_weekly_private_slot_publishes_private_reservation():
    # Wed 09:00 unlocks Sun 09:00, 72 hours earlier.
    result = _book(
        {"source": "weekly", "activity": "court1", "weekday": "Wed", "time": "09:00"},
        now=datetime(2026, 9, 27, 8, 59, tzinfo=TZ),
    )
    assert result.status == BOOKED
    assert result.target_date == "2026-09-30"
    assert result.calendar_reservation["visibility"] == "private"
    assert result.calendar_reservation["title"] == "Coaching"


def test_weekly_payload_cannot_choose_visibility():
    result = _book(
        {
            "source": "weekly",
            "activity": "court1",
            "weekday": "Mon",
            "time": "17:00",
            "visibility": "private",
            "title": "Coaching",
        },
        now=datetime(2026, 9, 25, 16, 59, tzinfo=TZ),
    )
    assert result.status == BOOKED
    assert result.calendar_reservation["visibility"] == "public"
    assert "title" not in result.calendar_reservation


@pytest.mark.parametrize(
    ("activity", "time", "visibility"),
    [("court1", "09:00", "private"), ("court1", "10:00", "public"), ("court2", "09:00", "public")],
)
def test_adhoc_booking_is_classified(activity, time, visibility):
    result = _book({"source": "adhoc", "activity": activity, "date": "2026-10-02", "time": time})
    assert result.status == BOOKED
    assert result.calendar_reservation["visibility"] == visibility
    assert ("title" in result.calendar_reservation) == (visibility == "private")


def test_writer_round_trips_private_metadata(monkeypatch, repo):
    monkeypatch.setattr(calendar_writer, "CalendarRepository", lambda: repo)
    result = _book({"source": "adhoc", "activity": "court1", "date": "2026-09-30", "time": "09:00"})
    calendar_writer.lambda_handler(
        {"status": result.status, "calendar_reservation": result.calendar_reservation}, None
    )
    stored = repo.snapshot()[result.reservation_id]
    assert stored["visibility"] == "private"
    assert stored["title"] == "Coaching"


def test_contract_validates_visibility_and_omits_empty_title():
    base = dict(
        reservation_id=1,
        equipment_id=7412,
        court="Court 1",
        start="2026-01-12 17:00:00",
        end="2026-01-12 18:00:00",
    )
    public = normalize_reservation(**base)
    assert public["visibility"] == "public"
    assert "title" not in public
    assert "title" not in normalize_reservation(**base, title="  ")
    with pytest.raises(ValueError, match="visibility"):
        normalize_reservation(**base, visibility="friends")


# --- repository and reconciliation -----------------------------------------


def _reservation(id="1", **kwargs):
    return normalize_reservation(
        reservation_id=id,
        equipment_id=7412,
        start="2026-09-30T11:30:00Z",
        end="2026-09-30T12:30:00Z",
        court=COURT1,
        **kwargs,
    )


def test_private_is_sticky_and_keeps_title(repo):
    repo.put_reservation(_reservation(visibility="private", title="Coaching"), now=NOW)
    first = repo.snapshot()["1"]
    assert not repo.put_reservation(_reservation(), now=NOW + timedelta(seconds=1))
    kept = repo.snapshot()["1"]
    assert kept["visibility"] == "private"
    assert kept["title"] == "Coaching"
    assert kept["sequence"] == first["sequence"]


def test_legacy_record_reads_public_without_revision(repo):
    reservation = _reservation()
    legacy = {k: v for k, v in reservation.items() if k != "visibility"}
    repo.table.put_item(
        Item={
            "PK": "CALENDAR",
            "SK": "RES#1",
            **legacy,
            "version": "v0",
            "sequence": 0,
            "created_at": NOW.isoformat(),
            "updated_at": NOW.isoformat(),
        }
    )
    assert not repo.put_reservation(reservation, now=NOW + timedelta(seconds=1))
    stored = repo.snapshot()["1"]
    assert stored["visibility"] == "public"
    assert stored["sequence"] == 0
    assert stored["updated_at"] == NOW.isoformat()


def _sync(repo, rows, now=NOW):
    session = SimpleNamespace(login=lambda *_: None, reservations=lambda *_: rows)
    return reconcile(
        repo,
        session,
        _config(),
        SimpleNamespace(username="x", password="y"),
        repo.claim_refresh(now=now, force=True),
        now=now,
    )


def _row(id, start, end, equipment_id=7412):
    return HeldReservation(id, equipment_id, None, start, end)


def test_reconcile_classifies_private_rows():
    with mock_aws():
        repo = make_repo()
        _sync(
            repo,
            [
                _row(1, "2026-09-30 09:00:00", "2026-09-30 10:00:00"),
                _row(2, "2026-09-30 10:00:00", "2026-09-30 11:00:00"),
                _row(3, "2026-09-30 09:00:00", "2026-09-30 10:00:00", equipment_id=12739),
            ],
        )
        stored = repo.snapshot()
        assert (stored["1"]["visibility"], stored["1"]["title"]) == ("private", "Coaching")
        assert stored["2"]["visibility"] == "public" and "title" not in stored["2"]
        assert stored["3"]["visibility"] == "public" and "title" not in stored["3"]


def test_reconcile_never_downgrades_private_and_cancellation_keeps_it(repo):
    # A booked private record at a time no rule matches (e.g. the rule moved).
    moved = normalize_reservation(
        reservation_id="7",
        equipment_id=7412,
        start="2026-10-01 12:00:00",
        end="2026-10-01 13:00:00",
        court=COURT1,
        visibility="private",
        title="Coaching",
    )
    repo.put_reservation(moved, now=NOW)
    _sync(repo, [_row(7, "2026-10-01 12:00:00", "2026-10-01 13:00:00")])
    assert repo.snapshot()["7"]["visibility"] == "private"
    assert repo.snapshot()["7"]["sequence"] == 0
    _sync(repo, [])
    cancelled = repo.snapshot()["7"]
    assert cancelled["status"] == "cancelled"
    assert (cancelled["visibility"], cancelled["title"]) == ("private", "Coaching")


# --- subscriptions and feed ------------------------------------------------


def test_subscription_scope_create_list_and_legacy(repo):
    public = repo.create_subscription("friend", now=NOW)
    private = repo.create_subscription("me", scope="private", now=NOW)
    assert public["scope"] == "public" and private["scope"] == "private"
    assert repo.validate_token(public["token"]) == "public"
    assert repo.validate_token(private["token"]) == "private"
    assert repo.validate_token(private["token"] + "x") is None
    with pytest.raises(ValueError, match="scope"):
        repo.create_subscription("x", scope="admin")
    # Created before scopes existed: no scope attribute at all.
    legacy = repo.create_subscription("owner", now=NOW)
    repo.table.update_item(
        Key={"PK": "SUBSCRIPTIONS", "SK": legacy["id"]}, UpdateExpression="REMOVE #s",
        ExpressionAttributeNames={"#s": "scope"},
    )
    assert repo.validate_token(legacy["token"]) == "public"
    scopes = {item["label"]: item["scope"] for item in repo.list_subscriptions()}
    assert scopes == {"friend": "public", "me": "private", "owner": "public"}
    repo.revoke_subscription(private["id"])
    assert repo.validate_token(private["token"]) is None


def _events(response):
    calendar = Calendar.from_ical(response["body"])
    return str(calendar["X-WR-CALNAME"]), sorted(
        str(event["SUMMARY"]) for event in calendar.walk("VEVENT")
    )


def test_feed_scopes_private_events(repo):
    _sync(
        repo,
        [
            _row(1, "2026-09-30 09:00:00", "2026-09-30 10:00:00"),
            _row(2, "2026-09-30 10:00:00", "2026-09-30 11:00:00"),
        ],
    )
    friend = repo.create_subscription("friend")
    me = repo.create_subscription("me", scope="private")
    client = Mock()

    def feed(token):
        return serve({"pathParameters": {"token": token}}, repo, client, NOW)

    public = feed(friend["token"])
    private = feed(me["token"])
    assert _events(public) == ("Court bookings", [COURT1])
    assert _events(private) == (
        "Court bookings (private)",
        sorted([COURT1, f"Coaching - {COURT1}"]),
    )
    assert "Coaching" not in public["body"]
    assert public["headers"]["ETag"] != private["headers"]["ETag"]


def test_public_only_ics_is_unchanged():
    reservation = {
        **_reservation(),
        "updated_at": "2026-09-01T12:00:00Z",
        "sequence": 0,
    }
    legacy = {k: v for k, v in reservation.items() if k != "visibility"}
    assert render_calendar([reservation]) == render_calendar([legacy])
    assert b"X-WR-CALNAME:Court bookings\r\n" in render_calendar([reservation])


# --- operator CLI ----------------------------------------------------------


def test_cli_scope_flag(monkeypatch, capsys):
    repository = Mock()
    repository.create_subscription.return_value = {"id": "id", "label": "me", "token": "t"}
    repository.list_subscriptions.return_value = [
        {"id": "id", "label": "me", "scope": "private", "token_hash": "secret-hash"}
    ]
    monkeypatch.setattr(calendar_cli, "CalendarRepository", lambda: repository)
    base = ["--base-url", "https://example.com"]
    assert calendar_cli.main(["subscription", "create", "friend", *base]) == 0
    repository.create_subscription.assert_called_with("friend", scope="public")
    assert calendar_cli.main(["subscription", "create", "me", "--scope", "private", *base]) == 0
    repository.create_subscription.assert_called_with("me", scope="private")
    capsys.readouterr()
    assert calendar_cli.main(["subscription", "list"]) == 0
    out = capsys.readouterr().out
    assert '"scope": "private"' in out and "secret" not in out
    with pytest.raises(SystemExit):
        calendar_cli.main(["subscription", "create", "x", "--scope", "admin", *base])
