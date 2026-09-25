from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from booker.config import load_bookings
from booker.handler import run_booking
from booker.http import HeldReservation, UpaceHttpBooker
from booker.results import CANCELLED, NOT_FOUND, BookingResult
from booker.secrets import Credentials
from booker.stub import BookingRequest, StubUpace

CREDS = Credentials(username="user@example.com", password="secret")
BOOKINGS = Path(__file__).resolve().parents[5] / "ecr/court-booker/bookings.yaml"


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


class Session:
    def __init__(self, held):
        self.held = held
        self.cancelled_ids = []

    def login(self, username, password):
        pass

    def reservations(self, start, end):
        return list(self.held)

    def cancel(self, reservation_id):
        self.cancelled_ids.append(reservation_id)


HELD = HeldReservation(99, 12739, None, "2026-08-17 06:00:00", "2026-08-17 07:00:00")


def test_cancel_without_held_reservation_is_not_found_and_ok():
    session = Session([])
    result = UpaceHttpBooker(session_factory=lambda: session).cancel(_request(), CREDS)
    assert result.status == NOT_FOUND
    assert result.ok
    assert session.cancelled_ids == []


def test_cancel_skips_a_different_reservation():
    session = Session([HELD])
    result = UpaceHttpBooker(session_factory=lambda: session).cancel(
        _request(expected_reservation_id="100"), CREDS
    )
    assert result.status == NOT_FOUND
    assert result.message == "different reservation held; not cancelled"
    assert session.cancelled_ids == []


def test_cancel_with_matching_expected_id():
    session = Session([HELD])
    result = UpaceHttpBooker(session_factory=lambda: session).cancel(
        _request(expected_reservation_id="99"), CREDS
    )
    assert result.status == CANCELLED
    assert session.cancelled_ids == [99]


def test_not_found_counts_as_ok():
    assert BookingResult(status=NOT_FOUND, message="").ok


def test_adhoc_cancel_passes_expected_reservation_id():
    seen = []

    class Browser(StubUpace):
        def cancel(self, request, creds):
            seen.append(request.expected_reservation_id)
            return super().cancel(request, creds)

    event = {
        "source": "adhoc",
        "activity": "court1",
        "date": "2026-09-28",
        "time": "17:00",
        "cancel": True,
        "expected_reservation_id": 123,
    }
    now = datetime(2026, 9, 25, 12, tzinfo=ZoneInfo("America/St_Johns"))
    result = run_booking(event, config=load_bookings(BOOKINGS), creds=CREDS, browser=Browser(), now=now)
    assert result.status == CANCELLED
    assert seen == ["123"]
    stub = StubUpace("not_found")
    missing = run_booking(event, config=load_bookings(BOOKINGS), creds=CREDS, browser=stub, now=now)
    assert missing.status == NOT_FOUND
