from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from booker.config import load_bookings
from booker.handler import finalize_lambda, get_browser, parse_event, run_booking
from booker.http import UpaceHttpBooker
from booker.results import AUTH_FAIL, BOOKED, CLOSED, LATE, BookingFailed, BookingResult
from booker.secrets import Credentials
from booker.stub import StubUpace

TZ = ZoneInfo("America/St_Johns")
CREDS = Credentials(username="user@example.com", password="stub")
BOOKINGS = Path(__file__).resolve().parents[5] / "ecr/court-booker/bookings.yaml"


def _config():
    return load_bookings(BOOKINGS)


def test_parse_event_unwraps_body():
    assert parse_event('{"source":"weekly"}')["source"] == "weekly"
    assert parse_event({"body": '{"source":"adhoc"}'})["source"] == "adhoc"


def test_weekly_success_on_unlock_day():
    browser = StubUpace("success")
    now = datetime(2026, 8, 14, 17, 58, tzinfo=TZ)
    result = run_booking(
        {
            "source": "weekly",
            "activity": "court1",
            "weekday": "Mon",
            "time": "18:00",
        },
        config=_config(),
        creds=CREDS,
        browser=browser,
        now=now,
    )
    assert result.status == BOOKED
    assert result.target_date == "2026-08-17"
    assert browser.reserve_clicks == 1


def test_closed_does_not_sleep_in_lambda():
    browser = StubUpace("closed")
    result = run_booking(
        {"source": "weekly", "activity": "court1", "weekday": "Mon", "time": "18:00"},
        config=_config(),
        creds=CREDS,
        browser=browser,
        now=datetime(2026, 8, 14, 18, 0, tzinfo=TZ),
    )
    assert result.status == CLOSED
    assert browser.book_calls == 1
    assert browser.reserve_clicks == 0


def test_auth_fail_does_not_retry():
    browser = StubUpace("auth_fail")
    result = run_booking(
        {"source": "weekly", "activity": "court1", "weekday": "Mon", "time": "18:00"},
        config=_config(),
        creds=CREDS,
        browser=browser,
        now=datetime(2026, 8, 14, 18, 0, tzinfo=TZ),
    )
    assert result.status == AUTH_FAIL
    assert browser.book_calls == 1
    assert browser.reserve_clicks == 0


def test_late_invoke_refuses():
    result = run_booking(
        {"source": "weekly", "activity": "court1", "weekday": "Mon", "time": "18:00"},
        config=_config(),
        creds=CREDS,
        browser=StubUpace("success"),
        now=datetime(2026, 8, 15, 18, 0, tzinfo=TZ),
    )
    assert result.status == LATE


def test_finalize_lambda_succeeds_on_booked_and_already_held():
    booked = BookingResult(status=BOOKED, message="ok", target_date="2026-08-17", activity="court1", time="18:00")
    held = BookingResult(status="already_held", message="held", target_date="2026-08-17", activity="court1", time="18:00")
    assert finalize_lambda(booked)["status"] == BOOKED
    assert finalize_lambda(held)["status"] == "already_held"


def test_finalize_lambda_raises_on_booking_failures():
    for status in (AUTH_FAIL, CLOSED, LATE, "full", "membership", "unexpected_ui"):
        result = BookingResult(status=status, message=status, activity="court1", time="18:00")
        with pytest.raises(BookingFailed) as caught:
            finalize_lambda(result)
        assert caught.value.result == result
        assert status in str(caught.value)


def test_get_browser_is_http_only():
    assert isinstance(get_browser(), UpaceHttpBooker)
