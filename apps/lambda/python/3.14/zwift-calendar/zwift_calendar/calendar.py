"""Stable RFC 5545 publication; private score state never enters the feed."""

import hashlib
from datetime import timedelta

from icalendar import Calendar, Event

from .api import instant


def render(events):
    calendar = Calendar()
    calendar.add("prodid", "-//Zwift Race Calendar//EN")
    calendar.add("version", "2.0")
    calendar.add("x-wr-calname", "Zwift races and special events")
    for row in sorted(events, key=lambda e: (e["start"], e["id"])):
        event = Event()
        event.add("uid", row["id"] + "@zwift-calendar")
        category = row["band"] or "No score band"
        event.add("summary", f"{row['name']} [{category}, {row['group']}]")
        for name, key in (
            ("dtstart", "start"),
            ("dtend", "end"),
            ("dtstamp", "updated"),
            ("last-modified", "updated"),
            ("created", "created"),
        ):
            event.add(name, instant(row[key]))
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
        if row.get("score_basis") == "max30":
            description.append("Eligibility uses your 30-day maximum Racing Score.")
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


def reconcile(incoming, revisions, now):
    old = {
        k: v
        for k, v in revisions.items()
        if instant(v["start"]) >= now - timedelta(days=30)
    }
    events = []
    for event in incoming:
        row = event | {
            "end": (
                instant(event["start"])
                + timedelta(seconds=event["duration"]["seconds"])
            ).isoformat()
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
    body = render(events)
    return {
        "ics": body,
        "etag": '"' + hashlib.sha256(body.encode()).hexdigest() + '"',
        "last_success": now.timestamp(),
    }, old
