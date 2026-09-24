"""Validate public Upace responses before building a dated schedule."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import calendar
import re
import httpx

ZONE = ZoneInfo("America/St_Johns")
URL = "https://ymcanl.com/location/cpfy/"


def month_end(day):
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def rows(payload, key):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("Unsuccessful upstream response")
    result = payload.get(key)
    if not isinstance(result, list):
        raise ValueError("Missing upstream collection")
    for field in ("next", "next_page", "next_cursor", "has_more", "pagination", "links"):
        if payload.get(field):
            raise ValueError("Incomplete upstream response")
    if "total" in payload and payload["total"] != len(result):
        raise ValueError("Incomplete upstream count")
    return result


def identity(value):
    if type(value) is not int or value <= 0:
        raise ValueError("Missing upstream identity")
    return str(value)


def instant(day, value):
    if not isinstance(value, str):
        raise ValueError("Missing time")
    local = datetime.combine(day, time.fromisoformat(value), ZONE)
    # Do not guess ambiguous/nonexistent times across DST transitions.
    utc = local.astimezone(ZoneInfo("UTC"))
    if utc.astimezone(ZONE).replace(tzinfo=None) != local.replace(tzinfo=None):
        raise ValueError("Nonexistent local time")
    if local.utcoffset() != local.replace(fold=1).utcoffset():
        raise ValueError("Ambiguous local time")
    return utc.isoformat()


def event(key, day, start, end, name, category, room, description):
    begin, finish = instant(day, start), instant(day, end)
    if finish <= begin:
        raise ValueError("Invalid session interval")
    return dict(id=key, start=begin, end=finish, title=f"{category}: {name}",
                category=category, location=f"Ches Penney Family YMCA - {room}",
                description=description, url=URL, status="active")


def equipment_events(payload, day):
    events = []
    for row in rows(payload, "schedule"):
        equipment = row["equipment"]
        if type(equipment.get("gym_id")) is not int:
            raise ValueError("Missing facility")
        if equipment["gym_id"] != 785:
            continue
        name = equipment["name"]
        calm = "calm water swim" in name.lower()
        main = equipment.get("room_id") == 6091 and bool(re.search(r"lane swim\s*/\s*open|open swim", name, re.I))
        if re.search(r"female|women|private|restricted", name, re.I) or not (calm or main):
            continue
        equipment_id = identity(equipment["id"])
        blocks = row.get("block_schedules")
        if not isinstance(blocks, list):
            raise ValueError("Missing closure blocks")
        closed = []
        for block in blocks:
            identity(block["block_schedule_id"])
            if block["day_of_week"] not in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
                raise ValueError("Invalid block weekday")
            if block["day_of_week"] != day.strftime("%a"):
                continue
            values = []
            for field in ("start_time", "end_time"):
                raw = block[field]
                if " " in raw or "T" in raw:
                    parsed = datetime.fromisoformat(raw)
                    if parsed.date() != day or parsed.tzinfo is not None:
                        raise ValueError("Unexpected dated closure")
                    raw = parsed.time().isoformat()
                values.append(instant(day, raw))
            if values[1] <= values[0]:
                raise ValueError("Invalid closure interval")
            closed.append(values)
        slots = row.get("slots")
        if not isinstance(slots, list):
            raise ValueError("Missing slots")
        for slot in slots:
            if slot["day_of_week"] not in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
                raise ValueError("Invalid weekday")
            slot_id = identity(slot["id"])
            if slot["day_of_week"] != day.strftime("%a"):
                continue
            base = event(f"equipment:{equipment_id}:{slot_id}:{day}", day,
                         slot["start_time"], slot["end_time"], name,
                         "Calm Water" if calm else "Open Swim", equipment["room_name"],
                         "Drop-in activity; not a reservation. First come, first served. "
                         "Membership or admission requirements apply. Check the YMCA for closures.")
            intervals = [(base["start"], base["end"])]
            for lower, upper in sorted(closed):
                intervals = [(a, b) for start, end in intervals for a, b in
                             ([(start, end)] if upper <= start or lower >= end else
                              [(start, min(lower, end)), (max(upper, start), end)]) if a < b]
            for index, (start, end) in enumerate(intervals):
                events.append({**base, "id": base["id"] + (f":part{index}" if index else ""),
                               "start": start, "end": end})
    return events


def class_events(payload, day):
    events = []
    for row in rows(payload, "classes"):
        if type(row.get("gym_id")) is not int:
            raise ValueError("Missing facility")
        if row["gym_id"] != 785 or not re.search(r"adult\s+swim(?:ming)?\s+lessons?", row["name"], re.I):
            continue
        if row.get("date") != day.isoformat():
            raise ValueError("Incorrect occurrence date")
        for key in ("cancelled", "facility_closed"):
            if type(row.get(key)) is not bool:
                raise ValueError("Missing closure state")
        if row["cancelled"] or row["facility_closed"]:
            continue
        if not date.fromisoformat(row["start_day"]) <= day <= date.fromisoformat(row["end_day"]):
            raise ValueError("Occurrence outside published season")
        events.append(event(f"class:{identity(row['id'])}:{identity(row['slot_id'])}:{day}",
                            day, row["start_time"], row["end_time"], row["name"],
                            "Adult Lesson", row["room_name"],
                            "Published lesson session; you are not registered. Registration and an active "
                            "membership may be required. See the YMCA for eligibility, fees and availability."))
    return events


class Upace:
    def __init__(self):
        self.client = httpx.Client(base_url="https://upace.app/api/", timeout=httpx.Timeout(20, connect=5),
                                   headers={"Origin": "https://embed.upace.app", "Accept": "application/json"})

    def close(self):
        self.client.close()

    def get(self, path, params, source):
        response = self.client.get(path, params=params, headers={"X-SOURCE": source})
        response.raise_for_status()
        return response.json()

    def collect(self, start, end, remaining=lambda: 600_000):
        collected = {}
        day = start
        while day < end:
            if remaining() < 50_000:
                raise TimeoutError("Insufficient time to complete snapshot")
            # Query one date at a time: a weekly response can include templates
            # that expire partway through the week.
            schedule = self.get("equipment/schedules/unauth", dict(university_id=105,
                                facility_id=785, start_date=str(day), end_date=str(day)), "SCHEDULE")
            classes = self.get("classes/list/unauth", dict(university_id=105, gym_id=785,
                               date=str(day)), "EMBED")
            for item in equipment_events(schedule, day) + class_events(classes, day):
                if item["id"] in collected:
                    raise ValueError("Duplicate source identity")
                collected[item["id"]] = item
            day += timedelta(days=1)
        return collected


class SwimmingSources:
    """Collect all sources completely before any snapshot can be published."""
    def __init__(self):
        from swim_calendar.city import PaulReynolds
        self.sources = [Upace()]
        try:
            self.sources.append(PaulReynolds())
        except Exception:
            self.close()
            raise

    def close(self):
        for source in self.sources:
            source.close()

    def collect(self, start, end, remaining=lambda: 600_000):
        result = {}
        for source in self.sources:
            fresh = source.collect(start, end, remaining)
            if result.keys() & fresh.keys():
                raise ValueError("Overlapping swimming source identities")
            result.update(fresh)
        return result
