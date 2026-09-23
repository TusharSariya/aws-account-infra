from datetime import date

from booker.http import (
    HeldReservation,
    UpaceHttpBooker,
    UpaceHttpError,
    _reservation_id,
)
from booker.results import ALREADY_HELD, AUTH_FAIL, BOOKED, CANCELLED, CLOSED, DRY_RUN, FULL
from booker.secrets import Credentials
from booker.stub import BookingRequest

CREDS = Credentials(username="user@example.com", password="secret")


def _request(**overrides) -> BookingRequest:
    values = dict(
        activity_key="court2",
        activity_label="Court 2",
        target_date=date(2026, 8, 17),
        hhmm="06:00",
        duration_min=60,
        people=1,
        equipment_id=12739,
    )
    values.update(overrides)
    return BookingRequest(**values)


class FakeSession:
    def __init__(
        self,
        *,
        login_error: UpaceHttpError | None = None,
        durations: list[int] | None = None,
        held: list[HeldReservation] | None = None,
        reserve_error: UpaceHttpError | None = None,
    ) -> None:
        self.login_error = login_error
        self.durations = durations if durations is not None else [60]
        self.held = held or []
        self.reserve_error = reserve_error
        self.reserve_calls = 0
        self.cancel_calls = 0
        self.cancelled_ids: list[int] = []

    def login(self, username: str, password: str) -> None:
        if self.login_error:
            raise self.login_error

    def available_duration_values(self, equipment_id: int, target_date: date, hhmm: str) -> list[int]:
        return list(self.durations)

    def reservations(self, start: date, end: date) -> list[HeldReservation]:
        return list(self.held)

    def reserve(self, **kwargs) -> int:
        self.reserve_calls += 1
        if self.reserve_error:
            raise self.reserve_error
        return 2176741740

    def cancel(self, reservation_id: int) -> None:
        self.cancel_calls += 1
        self.cancelled_ids.append(reservation_id)


def test_books_when_duration_is_offered():
    session = FakeSession()
    result = UpaceHttpBooker(session_factory=lambda: session).book(_request(), CREDS)
    assert result.status == BOOKED
    assert session.reserve_calls == 1


def test_empty_durations_is_closed():
    session = FakeSession(durations=[])
    result = UpaceHttpBooker(session_factory=lambda: session).book(_request(hhmm="20:00"), CREDS)
    assert result.status == CLOSED
    assert session.reserve_calls == 0


def test_missing_duration_is_full():
    session = FakeSession(durations=[30])
    result = UpaceHttpBooker(session_factory=lambda: session).book(_request(), CREDS)
    assert result.status == FULL
    assert session.reserve_calls == 0


def test_auth_fail_on_401():
    session = FakeSession(login_error=UpaceHttpError(401, "invalid credentials"))
    result = UpaceHttpBooker(session_factory=lambda: session).book(_request(), CREDS)
    assert result.status == AUTH_FAIL
    assert session.reserve_calls == 0


def test_already_held_matches_equipment_and_start():
    session = FakeSession(
        held=[
            HeldReservation(
                id=1,
                equipment_id=12739,
                class_id=12739,
                start_time="2026-08-17 06:00:00",
            )
        ]
    )
    result = UpaceHttpBooker(session_factory=lambda: session).book(_request(), CREDS)
    assert result.status == ALREADY_HELD
    assert session.reserve_calls == 0


def test_dry_run_skips_reserve():
    session = FakeSession()
    result = UpaceHttpBooker(session_factory=lambda: session).book(_request(dry_run=True), CREDS)
    assert result.status == DRY_RUN
    assert session.reserve_calls == 0


def test_outside_hours_400_is_closed():
    session = FakeSession(
        reserve_error=UpaceHttpError(
            400, "The equipment is not open during the time you have requested this reservation!"
        )
    )
    result = UpaceHttpBooker(session_factory=lambda: session).book(_request(), CREDS)
    assert result.status == CLOSED


def test_reservation_id_accepts_boolean_success():
    assert (
        _reservation_id(
            {
                "success": True,
                "id": 2176741740,
                "message": "The reservation has been placed successfully",
                "data": {"reservation_id": 2176741740},
            }
        )
        == 2176741740
    )


def test_cancel_matching_reservation():
    session = FakeSession(
        held=[
            HeldReservation(
                id=99,
                equipment_id=None,
                class_id=12739,
                start_time="2026-08-17 06:00:00",
            )
        ]
    )
    result = UpaceHttpBooker(session_factory=lambda: session).cancel(_request(), CREDS)
    assert result.status == CANCELLED
    assert session.cancelled_ids == [99]


def test_booked_metadata_contains_identity_and_requested_interval():
    result = UpaceHttpBooker(session_factory=FakeSession).book(_request(), CREDS)
    assert result.reservation_id == "2176741740"
    assert result.calendar_reservation["reservation_id"] == result.reservation_id
    assert result.calendar_reservation["start"] == "2026-08-17T08:30:00+00:00"
    assert result.calendar_reservation["end"] == "2026-08-17T09:30:00+00:00"


def test_held_metadata_preserves_actual_duration_and_cancellation():
    session = FakeSession(held=[HeldReservation(99, 12739, None,
        "2026-08-17 06:00:00", "2026-08-17 07:30:00")])
    booker = UpaceHttpBooker(session_factory=lambda: session)
    held = booker.book(_request(duration_min=60), CREDS)
    assert held.calendar_reservation["end"] == "2026-08-17T10:00:00+00:00"
    assert held.reservation_id == "99"
    cancelled = booker.cancel(_request(), CREDS)
    assert cancelled.calendar_reservation["status"] == "cancelled"
    assert cancelled.calendar_reservation["reservation_id"] == "99"


def test_held_dry_run_does_not_publish():
    session = FakeSession(held=[HeldReservation(99, 12739, None,
        "2026-08-17 06:00:00", "2026-08-17 07:30:00")])
    result = UpaceHttpBooker(session_factory=lambda: session).book(_request(dry_run=True), CREDS)
    assert result.status == DRY_RUN
    assert result.calendar_reservation is None


def test_missing_actual_end_is_not_guessed():
    session = FakeSession(held=[HeldReservation(99, 12739, None, "2026-08-17 06:00:00")])
    result = UpaceHttpBooker(session_factory=lambda: session).book(_request(), CREDS)
    assert result.reservation_id == "99"
    assert result.calendar_reservation is None


def test_cancelled_reservation_does_not_match():
    session = FakeSession(held=[HeldReservation(99, 12739, None,
        "2026-08-17 06:00:00", "2026-08-17 07:00:00", cancelled=True)])
    result = UpaceHttpBooker(session_factory=lambda: session).book(_request(), CREDS)
    assert result.status == BOOKED


def test_reservations_validator_fails_closed():
    import pytest
    from booker.http import _validated_reservations

    valid = {"id": 99, "class_id": 12739, "start_time": "2026-08-17 06:00:00",
             "end_time": "2026-08-17 07:00:00", "active": 1, "deleted": 0}
    assert _validated_reservations({"success": True, "data": {"reservations": []}}) == []
    assert _validated_reservations({"success": True, "data": {"reservations": [valid]}})[0].end_time == valid["end_time"]
    for payload in ({}, {"success": False, "data": {"reservations": []}},
                    {"success": True, "data": {}},
                    {"success": True, "data": {"reservations": [valid, {}]}},
                    {"success": True, "data": {"reservations": [valid], "total": 2}},
                    {"success": True, "data": {"reservations": [], "has_more": True}}):
        with pytest.raises(UpaceHttpError):
            _validated_reservations(payload)


def test_failed_reservation_read_never_attempts_booking():
    class FailedSession(FakeSession):
        def reservations(self, start, end):
            raise UpaceHttpError(502, "malformed")
    session = FailedSession()
    result = UpaceHttpBooker(session_factory=lambda: session).book(_request(), CREDS)
    assert not result.ok
    assert result.calendar_reservation is None
    assert session.reserve_calls == 0


def test_raw_reservations_rejects_failure_and_preserves_pagination_metadata(monkeypatch):
    import json
    import sys
    from types import SimpleNamespace

    import pytest
    from booker.http import GeneratedUpaceSession

    monkeypatch.setitem(sys.modules, "upace", SimpleNamespace(ApiException=RuntimeError))
    adapter = object.__new__(GeneratedUpaceSession)
    calls = []

    def response(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status=200, read=lambda: json.dumps({
            "success": True, "data": {"reservations": [], "next_cursor": "more"}
        }).encode())

    adapter._reservations = SimpleNamespace(list_my_reservations_without_preload_content=response)
    with pytest.raises(UpaceHttpError, match="incomplete"):
        adapter.reservations(date(2026, 8, 17), date(2026, 8, 18))
    assert calls[0]["_request_timeout"] == (5, 20)


def test_validator_recognizes_all_documented_cancellation_states():
    from booker.http import _validated_reservations

    base = {"id": 99, "class_id": 12739, "start_time": "2026-08-17 06:00:00",
            "end_time": "2026-08-17 07:00:00", "active": 1, "deleted": 0}
    for override in ({"active": 0}, {"deleted": 1}, {"cancelled_on": "2026-08-15 10:00:00"}):
        rows = _validated_reservations({"success": True, "data": {"reservations": [base | override]}})
        assert rows[0].cancelled
