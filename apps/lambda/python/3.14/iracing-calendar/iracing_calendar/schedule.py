"""Public schedule normalization. Track simulation timestamps are never starts."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta

CATEGORIES = {"OVAL", "SPORTS CAR", "FORMULA CAR"}
DAYS = {
    name: i for i, name in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))
}
DAY_PATTERN = r"\b(mon(?:day)?|tue(?:sday)?|wed(?:s|nesday)?|thu(?:r|rs|rsday)?|fri(?:day)?|sat(?:urday)?s?|sun(?:day)?s?)\b"


def race_slots(frequency):
    """None means explicit unknown; [] means continuous/non-race; tuples are UTC."""
    text = frequency.lower().strip()
    if re.search(r"qualifier|practice|qualifying.only", text):
        return []
    if re.search(
        r"hourly|every\s+(?:(?:even|odd)\s+)?(?:\d+\s+)?hours?\b|every (?:30|thirty) min|at :15 and :45",
        text,
    ):
        return []
    if not text or re.fullmatch(
        r"(?:\d+|four|five) timeslots per (?:race )?week", text
    ):
        return None
    if "gmt" not in text and "utc" not in text:
        raise ValueError(f"Unrecognized race schedule: {frequency}")
    if re.search(r"\bdaily\b|every day", text):
        text = re.sub(
            r"\bdaily\b|every day",
            "Monday Tuesday Wednesday Thursday Friday Saturday Sunday",
            text,
        ).lower()
    residue = re.sub(r"\([^)]*\)", "", text)
    residue = re.sub(DAY_PATTERN, "", residue)
    residue = re.sub(
        r"\b(?:races?|every|other|on|at|and|gmt|utc)\b|[\d\s,:;&.\-]", "", residue
    )
    if residue:
        raise ValueError(f"Unrecognized schedule qualifier: {frequency}")
    matches = list(re.finditer(DAY_PATTERN, text))
    if not matches:
        raise ValueError(f"Missing days: {frequency}")
    slots, pending = [], []
    for index, match in enumerate(matches):
        pending.append(DAYS[match[1][:3]])
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segment = text[match.end() : end]
        # Ignore parenthesized display conversions; only use stated UTC/GMT values.
        segment = re.sub(r"\([^)]*\)", "", segment)
        times = re.findall(r"\b(\d{1,2})(?::(\d{2}))?\b", segment)
        if not times:
            continue
        for hour, minute in times:
            hour, minute = int(hour), int(minute or 0)
            if hour > 23 or minute > 59:
                raise ValueError(f"Invalid start time: {frequency}")
            slots.extend((day, hour, minute) for day in pending)
        pending = []
    if pending or not slots:
        raise ValueError(f"Incomplete race schedule: {frequency}")
    return sorted(set(slots))


def week_start(value):
    day = date.fromisoformat(value)
    return day - timedelta(days=(day.weekday() - 1) % 7)


def occurrences(series, overrides=None):
    """Published rounds anchor alternating weeks; never synthesize missing weeks."""
    result = []
    season = re.search(r"20\d{2}(?: Season(?: \d+)?)?", series["name"])
    if not season:
        raise ValueError("Missing series coverage")
    coverage = "series:" + season[0]
    base_name = re.sub(r"\s*-?\s*20\d{2} Season(?: \d+)?", "", series["name"]).strip(
        " -"
    )
    default = race_slots(series["frequency"])
    if default == []:
        return []
    for rnd in series["weeks"]:
        start = week_start(rnd["date"])
        override = (overrides or {}).get((base_name, start.isoformat()))
        slots, link = override if override else (default, "")
        sources = sorted(set(series["sources"] + ([link] if link else [])))
        common = {
            "coverage": coverage,
            "round_id": f"{base_name}|{season[0]}|{rnd['week']}",
            "name": base_name,
            "track": rnd["track"],
            "cars": rnd.get("car", series["cars"]),
            "length": rnd["laps"],
            "eligibility": series["license"],
            "sources": sources,
        }
        if slots is None:
            result.append(
                common
                | {
                    "id": common["round_id"] + "|0",
                    "start": rnd["date"],
                    "end": (start + timedelta(days=7)).isoformat(),
                    "all_day": True,
                }
            )
            continue
        for slot_index, (day, hour, minute) in enumerate(
            sorted(slots, key=lambda s: ((s[0] - 1) % 7, s[1], s[2]))
        ):
            when = datetime.combine(
                start + timedelta(days=(day - 1) % 7), time(hour, minute), UTC
            )
            duration = re.fullmatch(
                r"(\d+)\s*(mins?|minutes?|hours?)", rnd["laps"], re.IGNORECASE
            )
            end = None
            if duration:
                minutes = int(duration[1]) * (
                    60 if duration[2].lower().startswith("hour") else 1
                )
                end = (when + timedelta(minutes=minutes)).isoformat()
            result.append(
                common
                | {
                    "id": common["round_id"] + f"|{slot_index}",
                    "start": when.isoformat(),
                    "end": end,
                    "all_day": False,
                }
            )
    return result
