from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

from booker.config import load_bookings
from booker.handler import get_browser, run_booking
from booker.schedule import parse_hhmm
from booker.secrets import load_credentials
from booker.stub import BookingRequest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m booker", description="Book a Ches Penney court via Upace.")
    parser.add_argument("--activity", help="Activity key from bookings.yaml (court1, court2)")
    parser.add_argument("--date", help="Target date YYYY-MM-DD (adhoc)")
    parser.add_argument("--time", dest="hhmm", help="Start time HH:MM 24h")
    parser.add_argument("--duration", type=int, default=60, help="Duration minutes (default 60)")
    parser.add_argument("--people", type=int, default=1, help="People attending (default 1)")
    parser.add_argument("--weekly", action="store_true", help="Resolve and book each enabled weekly rule")
    parser.add_argument("--dry-run", action="store_true", help="Fill the form but do not click Reserve")
    parser.add_argument("--cancel", action="store_true", help="Cancel the matching reservation only")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "calendar":
        from booker.calendar_cli import main as calendar_main

        return calendar_main(argv)
    args = build_parser().parse_args(argv)
    config = load_bookings()
    creds = load_credentials()
    browser = get_browser()
    tz = ZoneInfo(config.timezone)
    now = datetime.now(tz)

    if args.weekly:
        rules = [rule for rule in config.weekly if rule.enabled] or config.weekly
        results = []
        for rule in rules:
            event = {
                "source": "weekly",
                "activity": rule.activity,
                "weekday": rule.weekday,
                "time": rule.time,
                "duration_min": rule.duration_min,
                "people": rule.people,
                "wait": False,
                "dry_run": args.dry_run,
            }
            results.append(run_booking(event, config=config, creds=creds, browser=browser, now=now))
        return _emit(results, as_json=args.json)

    if not args.activity or not args.date or not args.hhmm:
        print("adhoc book needs --activity, --date, and --time (or pass --weekly)", file=sys.stderr)
        return 2
    target_date = date.fromisoformat(args.date)
    visibility, title = config.visibility_for(
        args.activity, datetime.combine(target_date, parse_hhmm(args.hhmm))
    )
    request = BookingRequest(
        activity_key=args.activity,
        activity_label=config.activity_label(args.activity),
        target_date=target_date,
        hhmm=args.hhmm,
        duration_min=args.duration,
        people=args.people,
        dry_run=args.dry_run,
        calendar_url=config.calendar_url,
        equipment_id=config.equipment_id(args.activity),
        timezone=config.timezone,
        visibility=visibility,
        title=title,
    )
    result = browser.cancel(request, creds) if args.cancel else browser.book(request, creds)
    return _emit([result], as_json=args.json)


def _emit(results, *, as_json: bool) -> int:
    payload = [item.as_dict() for item in results]
    if as_json:
        print(json.dumps(payload if len(payload) != 1 else payload[0], indent=2))
    else:
        for item in results:
            print(f"{item.status}: {item.message}")
    return 0 if all(item.ok for item in results) else 1
