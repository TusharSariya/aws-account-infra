"""Stable RFC 5545 publication; private score state never enters the feed."""

import hashlib
from datetime import timedelta
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event

from .api import instant

CALENDAR_NAMES = {
    "banded": "Zwift - Banded races",
    "unbanded": "Zwift - Unbanded races",
}


def render(events, name="Zwift races and special events"):
    calendar = Calendar()
    calendar.add("prodid", "-//Zwift Race Calendar//EN")
    calendar.add("version", "2.0")
    calendar.add("x-wr-calname", name)
    for row in sorted(events, key=lambda e: (e["start"], e["id"])):
        event = Event()
        event.add("uid", row["id"] + "@zwift-calendar")
        category = row["band"] or "No score band"
        event.add("summary", f"{row['name']} [{category}, {row['group']}]")
        for property_name, key in (
            ("dtstart", "start"),
            ("dtend", "end"),
            ("dtstamp", "updated"),
            ("last-modified", "updated"),
            ("created", "created"),
        ):
            if row.get(key) is not None:
                event.add(property_name, instant(row[key]))
        event.add("sequence", row["sequence"])
        event.add("transp", "TRANSPARENT")
        event.add("location", "Zwift")
        event.add("url", row["url"])
        duration = row["duration"]
        description = [
            (
                f"Group {row['group']}; Racing Score band {row['band']}."
                if row["band"]
                else f"Group {row['group']}; no Racing Score band advertised. Entry eligibility does not imply a beginner pace."
            ),
            f"Duration: {duration['source']}.",
        ]
        if duration["seconds"] is None:
            description.append(
                "Start-only event; no supported finish time is available."
            )
        else:
            minutes = duration["seconds"] / 60
            finish = instant(row["end"]).astimezone(ZoneInfo("America/St_Johns"))
            description.append(
                f"Central estimated ride time: {minutes:.1f} minutes; calendar end: {finish:%H:%M %Z}."
            )
            event.add("x-zwift-expected-duration-seconds", duration["seconds"])
            event.add(
                "x-zwift-reserved-duration-seconds",
                duration.get("reserved_seconds", duration["seconds"]),
            )
            if "lower_seconds" in duration:
                description.append(
                    f"Planning range: {duration['lower_seconds'] / 60:.1f}-{duration['upper_seconds'] / 60:.1f} minutes; reserves {duration['reserved_seconds'] / 60:g} minutes. Configured planning margin, not a statistical confidence interval."
                )
                event.add("x-zwift-planning-lower-seconds", duration["lower_seconds"])
                event.add("x-zwift-planning-upper-seconds", duration["upper_seconds"])
        if "power_source" in duration:
            description.append(
                "Community physics approximation, not Zwift's official engine. Baseline road bike; solo riding without drafting or powerups."
            )
            dates = duration["evidence_dates"]
            description.append(
                f"Contributing activities: {duration['activities']}"
                + (
                    f"; completed {dates[0]} to {dates[-1]}."
                    if dates
                    else "; default assumptions, not measured fitness."
                )
            )
            description.append(
                f"Activities supporting model durations: {duration['duration_support_min']}-{duration['duration_support_max']} per duration point."
            )
            if duration.get("sparse"):
                description.append("Sparse power evidence; wider planning margin.")
            if duration.get("assumed_endurance_exponent"):
                description.append(
                    "Endurance extension uses assumed power-law decline exponent 0.1."
                )
            if duration.get("collection_degraded"):
                description.append(
                    "Activity collection degraded; available in-window cached evidence used."
                )
            if duration.get("collection_incomplete"):
                description.append(
                    "Activity collection incomplete; remaining recordings will be retried hourly."
                )
        event.add("x-zwift-estimate-source", duration.get("category", "unknown"))
        if row.get("score_basis") == "max30":
            description.append("Eligibility uses your 30-day maximum Racing Score.")
        if row.get("event_kind", "race") == "race":
            turnout = row.get("turnout", {})
            average = turnout.get("average")
            if average is None:
                reason = {
                    "pending_history": "historical lookup pending",
                    "no_parent_link": "no recurring-parent link available",
                    "insufficient_history": "fewer than two comparable editions",
                }.get(turnout.get("reason"), "historical lookup pending")
                description.append(
                    f"Historical turnout in your division: unknown ({reason})."
                )
            else:
                description.append(
                    f"Expected finishers in your division: {average:.1f} (historical average across {turnout['editions']} recent comparable editions; same weekday/time; up to 90 days)."
                )
                event.add("x-zwift-average-finishers", f"{average:.1f}")
                event.add("x-zwift-turnout-editions", turnout["editions"])
        if row.get("special_event"):
            description.append("Special event: " + row["special_event"] + ".")
        if row.get("event_kind") == "special_ride":
            description.append(
                "Shortest eligible ride option: " + row["group_name"] + "."
            )
        if row.get("advertised_pace_upper"):
            description.append(
                f"Advertised group pace upper bound: {row['advertised_pace_upper']:g} W/kg; this is not a Racing Score category."
            )
        if duration["samples"]:
            description.append(
                f"Based on {duration['samples']} comparable finishers; actual finish time varies."
            )
        _, distance, laps, _ = row["signature"]
        if distance:
            description.append(f"Distance: {distance / 1000:g} km.")
        elif laps:
            description.append(f"Laps: {laps}.")
        if row["time_trial"]:
            description.append(
                "Time trial session opening; your assigned individual start may be later."
            )
        if row["provisional"]:
            description.append(
                "Provisional score filter; Zwift has not yet assigned a score. Confirm eligibility before joining."
            )
        if row["requirements"]:
            description.append("Event rules: " + ", ".join(row["requirements"]))
        description.append(row["url"])
        event.add("description", "\n".join(description))
        calendar.add_component(event)
    return calendar.to_ical().decode()


def reconcile(incoming, revisions, now, *, name="Zwift races and special events"):
    old = {
        k: v
        for k, v in revisions.items()
        if instant(v["start"]) >= now - timedelta(days=30)
    }
    events = []
    for event in incoming:
        row = event | {
            "presentation_version": 3,
            "end": (
                instant(event["start"])
                + timedelta(
                    seconds=event["duration"].get(
                        "reserved_seconds", event["duration"]["seconds"]
                    )
                )
            ).isoformat()
            if event["duration"]["seconds"] is not None
            else None,
        }
        prior = old.get(row["id"], {})
        changed = {
            k: v
            for k, v in prior.items()
            if k not in ("created", "updated", "sequence")
        } != row
        row.update(
            created=prior.get("created", now.isoformat()),
            updated=now.isoformat() if changed else prior["updated"],
            sequence=prior.get("sequence", -1) + int(changed),
        )
        old[row["id"]] = row
        events.append(row)
    body = render(events, name)
    return {
        "ics": body,
        "etag": '"' + hashlib.sha256(body.encode()).hexdigest() + '"',
        "last_success": now.timestamp(),
    }, old


def split_calendars(incoming, revisions, now):
    """Publish two disjoint subscriptions in one atomic public snapshot."""
    calendars = {}
    for key, name in CALENDAR_NAMES.items():
        rows = [
            event
            for event in incoming
            if (event["band"] is not None) == (key == "banded")
        ]
        snapshot, revisions = reconcile(rows, revisions, now, name=name)
        calendars[key] = {field: snapshot[field] for field in ("ics", "etag")}
    return {"calendars": calendars, "last_success": now.timestamp()}, revisions
