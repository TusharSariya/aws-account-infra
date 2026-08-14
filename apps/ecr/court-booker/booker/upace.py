from __future__ import annotations

import os
import re
from datetime import date, timedelta

from booker.results import (
    ALREADY_HELD,
    AUTH_FAIL,
    BOOKED,
    CANCELLED,
    CLOSED,
    DRY_RUN,
    FULL,
    MEMBERSHIP,
    UNEXPECTED_UI,
    BookingResult,
)
from booker.schedule import format_duration, format_people, format_ui_time, parse_hhmm
from booker.secrets import Credentials
from booker.stub import BookingRequest

TIMEOUT_MS = 20_000
AUTH_FAIL_COPY = "Your email or password is invalid"
MEMBERSHIP_COPY = "A valid and active membership is required"
CLOSED_COPY = "Past date - reservation closed"
SUCCESS_COPY = "Success"

# Lambda's /dev/shm is ~64MB and the sandbox cannot run. Without these flags
# Chromium dies at new_page() with "Assertion error" / "Target crashed".
LAMBDA_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--single-process",
    "--no-zygote",
    "--no-first-run",
    "--mute-audio",
    "--hide-scrollbars",
]


def in_lambda() -> bool:
    return bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


class UpaceBooker:
    """Drive embed.upace.app with Playwright. Lazy-imports playwright so the
    LocalStack zip (stub browser) does not need Chromium on the path.
    """

    def __init__(self, *, headless: bool | None = None) -> None:
        if headless is None:
            headless = os.environ.get("HEADLESS", "1") != "0"
        self.headless = headless

    def book(self, request: BookingRequest, creds: Credentials) -> BookingResult:
        return self._with_page(request, creds, self._book)

    def cancel(self, request: BookingRequest, creds: Credentials) -> BookingResult:
        return self._with_page(request, creds, self._cancel)

    def _with_page(self, request: BookingRequest, creds: Credentials, fn) -> BookingResult:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            launch_kwargs: dict = {"headless": self.headless}
            if in_lambda():
                launch_kwargs["chromium_sandbox"] = False
                launch_kwargs["args"] = list(LAMBDA_CHROMIUM_ARGS)
            browser = playwright.chromium.launch(**launch_kwargs)
            context = browser.new_context(
                locale="en-US",
                timezone_id="America/St_Johns",
            )
            page = context.new_page()
            try:
                return fn(page, request, creds)
            finally:
                context.close()
                browser.close()

    def _book(self, page, request: BookingRequest, creds: Credentials) -> BookingResult:
        meta = dict(
            target_date=request.target_date.isoformat(),
            activity=request.activity_key,
            time=request.hhmm,
        )
        self._open_calendar(page, request.calendar_url)
        unexpected = self._stop_if_unknown_challenge(page, meta)
        if unexpected:
            return unexpected
        self._goto_week(page, request.target_date)
        self._click_activity_for_day(page, request.activity_label, request.target_date)
        page.wait_for_timeout(500)
        if page.get_by_text(CLOSED_COPY, exact=False).count():
            return BookingResult(status=CLOSED, message=CLOSED_COPY, **meta)

        login = self._login_if_needed(page, creds, meta)
        if login:
            return login

        if self._already_held(page, request):
            return BookingResult(status=ALREADY_HELD, message="already in My Reservations", **meta)
        self._reopen_activity_if_needed(page, request)

        filled = self._fill_slot(page, request, meta)
        if filled:
            return filled
        if request.dry_run:
            return BookingResult(status=DRY_RUN, message="form filled, reserve skipped", **meta)

        reserve = page.get_by_role("button", name=re.compile(r"^Reserve$"))
        if not reserve.count():
            return BookingResult(status=UNEXPECTED_UI, message="Reserve button missing", **meta)
        if not reserve.first.is_enabled():
            return BookingResult(status=UNEXPECTED_UI, message="Reserve stayed disabled", **meta)
        reserve.first.click()
        page.wait_for_timeout(1000)
        if page.get_by_text(MEMBERSHIP_COPY, exact=False).count():
            return BookingResult(status=MEMBERSHIP, message=MEMBERSHIP_COPY, **meta)
        if page.get_by_text(SUCCESS_COPY, exact=False).count() == 0:
            return BookingResult(status=UNEXPECTED_UI, message="no Success dialog after Reserve", **meta)
        return BookingResult(status=BOOKED, message="reservation complete", reserve_clicks=1, **meta)

    def _cancel(self, page, request: BookingRequest, creds: Credentials) -> BookingResult:
        meta = dict(
            target_date=request.target_date.isoformat(),
            activity=request.activity_key,
            time=request.hhmm,
        )
        self._open_calendar(page, request.calendar_url)
        self._goto_week(page, request.target_date)
        self._click_activity_for_day(page, request.activity_label, request.target_date)
        page.wait_for_timeout(500)
        login = self._login_if_needed(page, creds, meta)
        if login:
            return login
        self._dismiss_booking_modal(page)
        row = self._reservation_row(page, request)
        if row is None:
            return BookingResult(status=UNEXPECTED_UI, message="matching reservation not found", **meta)
        row.get_by_text(re.compile(r"Cancel Reservation", re.I)).click()
        page.wait_for_timeout(1000)
        if self._reservation_row(page, request) is not None:
            return BookingResult(status=UNEXPECTED_UI, message="reservation row still present", **meta)
        return BookingResult(status=CANCELLED, message="cancelled matching reservation", **meta)

    def _open_calendar(self, page, url: str) -> None:
        page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        page.get_by_title("next week").wait_for(timeout=TIMEOUT_MS)

    def _goto_week(self, page, target: date) -> None:
        next_week = page.get_by_title("next week")
        for _ in range(4):
            if self._week_contains(page, target):
                return
            if next_week.count() == 0 or next_week.first.is_disabled():
                break
            next_week.first.click()
            page.wait_for_timeout(800)
        if not self._week_contains(page, target):
            raise RuntimeError(f"could not page to week containing {target.isoformat()}")

    def _week_contains(self, page, target: date) -> bool:
        body = page.inner_text("body")
        month = target.strftime("%b")
        return month in body and re.search(rf"\b{target.day}\b", body) is not None

    def _click_activity_for_day(self, page, activity_label: str, target: date) -> None:
        cards = page.get_by_text(activity_label, exact=False)
        if cards.count() == 0:
            raise RuntimeError(f"activity {activity_label!r} not on the calendar")
        monday = target - timedelta(days=target.weekday())
        index = (target - monday).days
        cards.nth(min(index, cards.count() - 1)).click()

    def _login_if_needed(self, page, creds: Credentials, meta: dict) -> BookingResult | None:
        password = page.locator('input[type="password"]')
        if password.count() == 0:
            return None
        email = page.locator('input[type="email"], input[name="email"], input[placeholder*="email" i]')
        email.first.fill(creds.username)
        password.first.fill(creds.password)
        page.get_by_role("button", name=re.compile(r"Login to Reserve", re.I)).click()
        page.wait_for_timeout(800)
        if page.get_by_text(AUTH_FAIL_COPY, exact=False).count():
            return BookingResult(status=AUTH_FAIL, message=AUTH_FAIL_COPY, **meta)
        page.get_by_role("combobox", name="Start Time").wait_for(timeout=TIMEOUT_MS)
        return None

    def _already_held(self, page, request: BookingRequest) -> bool:
        self._dismiss_booking_modal(page)
        held = self._reservation_row(page, request) is not None
        self._dismiss_reservations(page)
        return held

    def _reopen_activity_if_needed(self, page, request: BookingRequest) -> None:
        if page.get_by_role("combobox", name="Start Time").count():
            return
        self._goto_week(page, request.target_date)
        self._click_activity_for_day(page, request.activity_label, request.target_date)
        page.get_by_role("combobox", name="Start Time").wait_for(timeout=TIMEOUT_MS)

    def _dismiss_booking_modal(self, page) -> None:
        if page.get_by_role("combobox", name="Start Time").count() == 0:
            return
        close = page.get_by_role("button", name=re.compile(r"^Close$"))
        if close.count():
            close.first.click()
            page.wait_for_timeout(400)

    def _reservations_dialog(self, page):
        return page.get_by_role("dialog").filter(has_text=re.compile(r"My Reservations", re.I))

    def _dismiss_reservations(self, page) -> None:
        dialog = self._reservations_dialog(page)
        if dialog.count() == 0:
            return
        close = dialog.get_by_role("button", name=re.compile(r"^Close$"))
        if close.count():
            close.first.click()
            page.wait_for_timeout(400)

    def _fill_slot(self, page, request: BookingRequest, meta: dict) -> BookingResult | None:
        ui_time = format_ui_time(parse_hhmm(request.hhmm))
        page.get_by_role("combobox", name="Start Time").click()
        page.wait_for_timeout(300)
        slot = page.get_by_role("option").filter(
            has_text=re.compile(rf"{re.escape(ui_time)}.*spots remaining", re.I)
        )
        if slot.count() == 0:
            if page.get_by_role("option").filter(has_text=re.compile(rf"{re.escape(ui_time)}", re.I)).count():
                return BookingResult(status=FULL, message=f"{ui_time} has no open spots", **meta)
            return BookingResult(status=CLOSED, message=f"no start time {ui_time}", **meta)
        slot.first.click()
        page.wait_for_timeout(200)
        self._choose(page, "Duration", format_duration(request.duration_min))
        self._choose(page, "People Attending", format_people(request.people))
        return None

    def _choose(self, page, combobox_name: str, option_text: str) -> None:
        page.get_by_role("combobox", name=combobox_name).click()
        page.wait_for_timeout(200)
        page.get_by_role("option", name=option_text, exact=False).first.click()
        page.wait_for_timeout(200)

    def _reservation_row(self, page, request: BookingRequest):
        dialog = self._open_reservations(page)
        if dialog is None:
            return None
        ui_time = format_ui_time(parse_hhmm(request.hhmm))
        date_heading = request.target_date.strftime("%A, %B %-d")
        court = request.activity_label.split(" - ")[-1]
        time_re = re.compile(rf"{re.escape(ui_time)}\s*-", re.I)
        date_re = re.compile(re.escape(date_heading), re.I)
        court_re = re.compile(re.escape(court), re.I)
        heading_re = re.compile(
            r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+[A-Za-z]+\s+\d+",
            re.I,
        )
        current_date = ""
        rows = dialog.get_by_role("row")
        for i in range(rows.count()):
            row = rows.nth(i)
            text = " ".join(row.inner_text().split())
            if heading_re.fullmatch(text):
                current_date = text
                continue
            if time_re.search(text) and court_re.search(text) and re.search(r"Cancel Reservation", text, re.I):
                if date_re.search(current_date):
                    return row
        return None

    def _open_reservations(self, page):
        dialog = self._reservations_dialog(page)
        if dialog.count() == 0:
            link = page.get_by_text(re.compile(r"View my reservations", re.I))
            if link.count() == 0:
                return None
            link.first.click()
            dialog = self._reservations_dialog(page)
            dialog.wait_for(timeout=TIMEOUT_MS)
        try:
            dialog.get_by_text(re.compile(r"Cancel Reservation", re.I)).first.wait_for(timeout=TIMEOUT_MS)
        except Exception:
            return dialog
        return dialog

    def _stop_if_unknown_challenge(self, page, meta: dict) -> BookingResult | None:
        body = page.inner_text("body")
        for needle in ("captcha", "verify you are human", "enter the pin", "two-factor", "authenticator"):
            if needle in body.lower():
                return BookingResult(status=UNEXPECTED_UI, message=f"challenge: {needle}", **meta)
        return None
