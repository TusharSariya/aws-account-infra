from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from booker.config import BookingsConfig, load_bookings
from booker.results import LATE, BookingFailed, BookingResult
from booker.schedule import resolve_weekly_target
from booker.secrets import Credentials, load_credentials
from booker.stub import BookingRequest, StubUpace
from booker.timing import Stopwatch


def parse_event(event: Any) -> dict[str, Any]:
    if event is None:
        return {}
    if isinstance(event, str):
        event = json.loads(event)
    if not isinstance(event, dict):
        raise TypeError(f"event must be a dict, got {type(event).__name__}")
    # Function URL / API Gateway wrap the body; Scheduler sends the payload as-is.
    if "body" in event and "source" not in event:
        body = event["body"]
        if isinstance(body, str):
            body = json.loads(body or "{}")
        if isinstance(body, dict):
            return body
    return event


def get_browser():
    mode = os.environ.get("BOOKER_BROWSER", "playwright").strip().lower()
    if mode == "stub":
        return StubUpace(scenario=os.environ.get("BOOKER_STUB_SCENARIO", "success"))
    if mode == "api":
        from booker.http import UpaceHttpBooker

        return UpaceHttpBooker()
    from booker.upace import UpaceBooker

    return UpaceBooker()


def run_booking(
    event: dict[str, Any],
    *,
    config: BookingsConfig,
    creds: Credentials,
    browser,
    now: datetime,
) -> BookingResult:
    source = str(event.get("source") or "weekly")
    if source == "weekly":
        return _run_weekly(event, config=config, creds=creds, browser=browser, now=now)
    if source == "adhoc":
        return _run_adhoc(event, config=config, creds=creds, browser=browser)
    raise ValueError(f"unknown event source {source!r}")


def _run_weekly(
    event: dict[str, Any],
    *,
    config: BookingsConfig,
    creds: Credentials,
    browser,
    now: datetime,
) -> BookingResult:
    activity = str(event["activity"])
    weekday = str(event.get("weekday") or "")
    hhmm = str(event.get("time") or "")
    duration_min = int(event.get("duration_min") or 60)
    people = int(event.get("people") or 1)
    if not weekday or not hhmm:
        rule = next((item for item in config.weekly if item.activity == activity), None)
        if rule is None:
            raise ValueError(f"no weekly rule for activity {activity!r}")
        weekday = weekday or rule.weekday
        hhmm = hhmm or rule.time
        duration_min = int(event.get("duration_min") or rule.duration_min)
        people = int(event.get("people") or rule.people)

    target = resolve_weekly_target(
        weekday=weekday,
        hhmm=hhmm,
        now=now,
        horizon_hours=config.horizon_hours,
        require_unlock_day=True,
    )
    if target.late:
        return BookingResult(
            status=LATE,
            message=f"invoke day {now.strftime('%a')} is not unlock day {target.weekday} minus 3d",
            target_date=target.target_date.isoformat(),
            activity=activity,
            time=hhmm,
        )
    request = BookingRequest(
        activity_key=activity,
        activity_label=config.activity_label(activity),
        target_date=target.target_date,
        hhmm=hhmm,
        duration_min=duration_min,
        people=people,
        dry_run=bool(event.get("dry_run", False)),
        calendar_url=config.calendar_url,
        equipment_id=config.equipment_id(activity),
    )
    return browser.book(request, creds)


def _run_adhoc(
    event: dict[str, Any],
    *,
    config: BookingsConfig,
    creds: Credentials,
    browser,
) -> BookingResult:
    activity = str(event["activity"])
    request = BookingRequest(
        activity_key=activity,
        activity_label=config.activity_label(activity),
        target_date=date.fromisoformat(str(event["date"])),
        hhmm=str(event["time"]),
        duration_min=int(event.get("duration_min") or 60),
        people=int(event.get("people") or 1),
        dry_run=bool(event.get("dry_run", False)),
        calendar_url=config.calendar_url,
        equipment_id=config.equipment_id(activity),
    )
    if event.get("cancel"):
        return browser.cancel(request, creds)
    return browser.book(request, creds)


def _now(tz) -> datetime:
    raw = os.environ.get("BOOKER_NOW", "").strip()
    if raw:
        return datetime.fromisoformat(raw).astimezone(tz)
    return datetime.now(tz)


def finalize_lambda(result: BookingResult) -> dict[str, Any]:
    payload = result.as_dict()
    print(json.dumps(payload), flush=True)
    if not result.ok:
        raise BookingFailed(result)
    return payload


def lambda_handler(event, context):  # noqa: ARG001
    clock = Stopwatch("lambda_handler")
    parsed = parse_event(event)
    clock.mark("parse_event")
    config = load_bookings()
    clock.mark("load_bookings")
    creds = load_credentials()
    clock.mark("load_credentials")
    browser = get_browser()
    clock.mark("get_browser", browser=type(browser).__name__)
    tz = ZoneInfo(config.timezone)
    now = _now(tz)
    result = run_booking(parsed, config=config, creds=creds, browser=browser, now=now)
    clock.mark("run_booking", status=result.status)
    return finalize_lambda(result)
