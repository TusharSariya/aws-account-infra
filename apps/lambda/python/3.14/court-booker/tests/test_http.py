from datetime import date

from booker.http import (
    HeldReservation,
    UpaceHttpBooker,
    UpaceHttpError,
    _reservation_id,
)
from booker.results import ALREADY_HELD, AUTH_FAIL, BOOKED, CANCELLED, CLOSED, DRY_RUN, FULL, RECONCILE
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


class FakeIdempotencyStore:
    def __init__(self, existing=None) -> None:
        self.existing = existing
        self.completed = []
        self.reconciled = []
        self.released = []

    def acquire(self, request):
        return self.existing

    def complete(self, request):
        self.completed.append(request)

    def reconcile(self, request, reason):
        self.reconciled.append((request, reason))

    def release(self, request):
        self.released.append(request)


def test_books_when_duration_is_offered():
    session = FakeSession()
    result = UpaceHttpBooker(session_factory=lambda: session).book(_request(), CREDS)
    assert result.status == BOOKED
    assert session.reserve_calls == 1


def test_successful_booking_completes_idempotency_record():
    session = FakeSession()
    store = FakeIdempotencyStore()
    result = UpaceHttpBooker(
        session_factory=lambda: session,
        idempotency_store=store,
    ).book(_request(), CREDS)
    assert result.status == BOOKED
    assert len(store.completed) == 1


def test_pending_booking_never_calls_reserve():
    session = FakeSession()
    store = FakeIdempotencyStore(existing="PENDING")
    result = UpaceHttpBooker(
        session_factory=lambda: session,
        idempotency_store=store,
    ).book(_request(), CREDS)
    assert result.status == RECONCILE
    assert session.reserve_calls == 0


def test_succeeded_booking_is_idempotent_success():
    session = FakeSession()
    store = FakeIdempotencyStore(existing="SUCCEEDED")
    result = UpaceHttpBooker(
        session_factory=lambda: session,
        idempotency_store=store,
    ).book(_request(), CREDS)
    assert result.status == ALREADY_HELD
    assert session.reserve_calls == 0


def test_ambiguous_reserve_failure_requires_reconciliation():
    session = FakeSession(reserve_error=UpaceHttpError(503, "upstream unavailable"))
    store = FakeIdempotencyStore()
    result = UpaceHttpBooker(
        session_factory=lambda: session,
        idempotency_store=store,
    ).book(_request(), CREDS)
    assert result.status == RECONCILE
    assert len(store.reconciled) == 1


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
