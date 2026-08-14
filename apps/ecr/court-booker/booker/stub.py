from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from booker.results import (
    ALREADY_HELD,
    AUTH_FAIL,
    BOOKED,
    CLOSED,
    FULL,
    MEMBERSHIP,
    UNEXPECTED_UI,
    BookingResult,
)
from booker.schedule import format_ui_time, parse_hhmm
from booker.secrets import Credentials


@dataclass
class BookingRequest:
    activity_key: str
    activity_label: str
    target_date: date
    hhmm: str
    duration_min: int
    people: int
    dry_run: bool = False
    calendar_url: str = ""


class StubUpace:
    """In-process Upace stand-in for LocalStack and unit tests. No Chromium."""

    def __init__(self, scenario: str = "success") -> None:
        self.scenario = scenario
        self.reserve_clicks = 0
        self.book_calls = 0
        self.cancel_calls = 0
        self._closed_once = False

    def book(self, request: BookingRequest, creds: Credentials) -> BookingResult:
        self.book_calls += 1
        target = request.target_date.isoformat()
        base = dict(
            target_date=target,
            activity=request.activity_key,
            time=request.hhmm,
        )
        if self.scenario == "auth_fail":
            return BookingResult(status=AUTH_FAIL, message="invalid credentials", **base)
        if self.scenario == "membership":
            return BookingResult(status=MEMBERSHIP, message="membership required", **base)
        if self.scenario == "already_held":
            return BookingResult(status=ALREADY_HELD, message="already held", **base)
        if self.scenario == "full":
            return BookingResult(status=FULL, message="slot full", **base)
        if self.scenario == "unexpected":
            return BookingResult(status=UNEXPECTED_UI, message="unknown dialog", **base)
        if self.scenario == "closed":
            return BookingResult(status=CLOSED, message="listing closed", **base)
        if self.scenario == "closed_then_open":
            if not self._closed_once:
                self._closed_once = True
                return BookingResult(status=CLOSED, message="listing closed", **base)
        if request.dry_run:
            return BookingResult(status="dry_run", message="form filled, reserve skipped", **base)
        self.reserve_clicks += 1
        ui = format_ui_time(parse_hhmm(request.hhmm))
        return BookingResult(
            status=BOOKED,
            message=f"reserved {request.activity_key} {target} {ui}",
            reserve_clicks=self.reserve_clicks,
            **base,
        )

    def cancel(self, request: BookingRequest, creds: Credentials) -> BookingResult:
        self.cancel_calls += 1
        return BookingResult(
            status="cancelled",
            message="cancelled matching reservation",
            target_date=request.target_date.isoformat(),
            activity=request.activity_key,
            time=request.hhmm,
        )
