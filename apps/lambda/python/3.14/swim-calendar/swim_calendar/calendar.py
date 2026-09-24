"""Idempotent event revisions and deterministic ICS output."""
from datetime import datetime, timedelta
import hashlib
from icalendar import Calendar, Event


def reconcile(old, fresh, now, start, end):
    result = {}
    timestamp = now.isoformat()
    for key, value in old.items():
        if datetime.fromisoformat(value["end"]) < now - timedelta(days=30):
            continue
        result[key] = dict(value)
    for key, item in fresh.items():
        previous = old.get(key)
        same = previous and all(previous.get(k) == v for k, v in item.items())
        result[key] = {**item, "created_at": previous["created_at"] if previous else timestamp,
                       "updated_at": previous["updated_at"] if same else timestamp,
                       "sequence": previous["sequence"] if same else (previous["sequence"] + 1 if previous else 0)}
    for key, item in result.items():
        # Keep past history; remove future sessions absent from the new window,
        # including a shrinking month boundary. Tombstones preserve identity.
        if key not in fresh and datetime.fromisoformat(item["start"]) >= start and item["status"] != "cancelled":
            item.update(status="cancelled", updated_at=timestamp, sequence=item["sequence"] + 1)
    return result


def render(events):
    calendar = Calendar()
    calendar.add("prodid", "-//YMCA Swim Calendar//EN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("x-wr-calname", "Ches Penney Swimming")
    for key, item in sorted(events.items()):
        if item["status"] != "active":
            continue
        event = Event()
        event.add("uid", hashlib.sha256(key.encode()).hexdigest() + "@ymca-swim-calendar")
        for field, source in (("dtstart", "start"), ("dtend", "end"), ("dtstamp", "updated_at"),
                              ("last-modified", "updated_at"), ("created", "created_at")):
            event.add(field, datetime.fromisoformat(item[source]))
        for field, source in (("summary", "title"), ("description", "description"),
                              ("location", "location"), ("url", "url"), ("categories", "category"),
                              ("sequence", "sequence")):
            event.add(field, item[source])
        event.add("transp", "TRANSPARENT")
        calendar.add_component(event)
    return calendar.to_ical().decode()
