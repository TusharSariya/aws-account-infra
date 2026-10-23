"""Coverage-aware reconciliation and deterministic RFC 5545 serialization."""

import hashlib
from datetime import date, datetime, timedelta

from icalendar import Calendar, Event

from .duration import describe


def render(events):
    calendar = Calendar()
    calendar.add("prodid", "-//Independent iRacing Calendar//EN")
    calendar.add("version", "2.0")
    calendar.add("x-wr-calname", "iRacing irregular races")
    for item in sorted(events, key=lambda e: (e["start"], e["id"])):
        event = Event()
        event.add(
            "uid", hashlib.sha256(item["id"].encode()).hexdigest() + "@iracing-calendar"
        )
        event.add("sequence", item["sequence"])
        event.add("dtstamp", datetime.fromisoformat(item["updated"]))
        event.add("last-modified", datetime.fromisoformat(item["updated"]))
        event.add("created", datetime.fromisoformat(item["created"]))
        event.add(
            "summary",
            item["name"] + (" - Start times unconfirmed" if item["all_day"] else ""),
        )
        parse = date.fromisoformat if item["all_day"] else datetime.fromisoformat
        event.add("dtstart", parse(item["start"]))
        if item.get("end"):
            event.add("dtend", parse(item["end"]))
        event.add("transp", "TRANSPARENT")
        event.add("location", item["track"])
        description = [
            f"{label}: {item[key]}"
            for label, key in (
                ("Cars", "cars"),
                ("Race length", "length"),
                ("Eligibility", "eligibility"),
            )
            if item.get(key)
        ]
        if item.get("description"):
            description.append(item["description"])
        if not item["all_day"] and item.get("duration"):
            description.append(describe(item["duration"]))
        if item["all_day"]:
            description.append("Start times unconfirmed.")
        description.extend(item["sources"])
        event.add("description", "\n".join(description))
        event.add("url", item["sources"][-1])
        calendar.add_component(event)
    return calendar.to_ical().decode()


def preserve_identities(old_events, incoming):
    """Keep unchanged starts' IDs when slots are inserted or removed; pair corrections."""
    groups = {}
    for event in incoming:
        groups.setdefault(event["round_id"], []).append(dict(event))
    output = []
    for round_id, new in groups.items():
        old = [e for e in old_events if e["round_id"] == round_id]
        available = {e["id"]: e for e in old}
        assigned, unmatched = [], []
        for event in new:
            match = next(
                (
                    e
                    for e in available.values()
                    if (e["start"], e["all_day"]) == (event["start"], event["all_day"])
                ),
                None,
            )
            if match:
                event["id"] = match["id"]
                available.pop(match["id"])
                assigned.append(event)
            else:
                unmatched.append(event)
        # A corrected start or a date placeholder becoming timed retains its UID.
        remaining = sorted(available.values(), key=lambda e: e["start"])
        used = {e["id"] for e in old} | {e["id"] for e in assigned}
        for index, event in enumerate(sorted(unmatched, key=lambda e: e["start"])):
            if index < len(remaining):
                event["id"] = remaining[index]["id"]
            else:
                ordinal = 0
                while f"{round_id}|{ordinal}" in used:
                    ordinal += 1
                event["id"] = f"{round_id}|{ordinal}"
            used.add(event["id"])
            assigned.append(event)
        output.extend(assigned)
    return output


def event_coverage(event):
    """Upgrade historical coverage without changing subscriber-visible revisions."""
    special = event.get("provenance", {}).get("special_id")
    if special and event["coverage"] == "special:" + special.split(":", 1)[0]:
        return event | {"coverage": "special:" + special}
    return event


def reconcile(previous, incoming, coverage, now):
    cutoff = (now - timedelta(days=30)).date().isoformat()
    old = {event["id"]: event_coverage(event) for event in previous.get("events", [])}
    result = {
        key: event for key, event in old.items() if event["coverage"] not in coverage
    }
    for item in preserve_identities(list(old.values()), incoming):
        if item["id"] in result:
            raise ValueError("Duplicate event identity")
        original = old.get(item["id"], {})
        details = {
            k: v
            for k, v in original.items()
            if k not in ("sequence", "created", "updated")
        }
        changed = details != item
        result[item["id"]] = item | {
            "sequence": original.get("sequence", -1) + int(changed),
            "created": original.get("created", now.isoformat()),
            "updated": now.isoformat() if changed else original["updated"],
        }
    result = {
        key: e
        for key, e in result.items()
        if (e.get("end") or e["start"])[:10] >= cutoff
    }
    events = sorted(result.values(), key=lambda e: e["id"])
    body = render(events)
    report = {
        "retained_unverified_ids": sorted(
            e["id"]
            for e in events
            if e["coverage"].startswith("special:") and e["coverage"] not in coverage
        ),
        "timed": sum(not e["all_day"] for e in events),
        "date_only": sum(e["all_day"] for e in events),
        "removed": len(old.keys() - result.keys()),
        "coverage": sorted(set(coverage) | {e["coverage"] for e in events}),
        "coverage_details": {
            scope: {
                "upcoming": sum(
                    e["coverage"] == scope and e["start"][:10] >= now.date().isoformat()
                    for e in events
                ),
                "latest_start": max(
                    (e["start"] for e in events if e["coverage"] == scope), default=None
                ),
            }
            for scope in sorted(set(coverage) | {e["coverage"] for e in events})
        },
        "upcoming": sum(e["start"][:10] >= now.date().isoformat() for e in events),
    }
    return {
        "events": events,
        "ics": body,
        "etag": '"' + hashlib.sha256(body.encode()).hexdigest() + '"',
        "last_success": now.timestamp(),
        "report": report,
    }
