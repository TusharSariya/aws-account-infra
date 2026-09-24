"""Bounded public downloads and literal-only application-data extraction."""

from __future__ import annotations

import base64
import io
import re
import time
from datetime import UTC, date, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import json5
from bs4 import BeautifulSoup
from pypdf import PdfReader

from .schedule import CATEGORIES, occurrences, race_slots, week_start

HUB = "https://iracinghub.com/"
PDF = "https://members-assets.iracing.com/public/schedulepdf/SeasonSchedule.pdf"
SPECIAL = "https://www.iracing.com/special-events/"
NEWS = "https://www.iracing.com/category/news/"
ALLOWED = {"iracinghub.com", "www.iracing.com", "members-assets.iracing.com"}


class Fetcher:
    def __init__(self, cache=None):
        self.cache = cache or {}
        self.used = {}
        self.requests = 0
        self.deadline = time.monotonic() + 420

    def get(self, url):
        if urlparse(url).scheme != "https" or urlparse(url).hostname not in ALLOWED:
            raise ValueError(f"Unsupported public source: {url}")
        if url in self.used:
            return base64.b64decode(self.used[url]["body"])
        self.requests += 1
        if self.requests > 24 or time.monotonic() > self.deadline:
            raise ValueError("Source request budget exceeded")
        old = self.cache.get(url, {})
        headers = {"User-Agent": "iracing-calendar/0.1 (public schedule reader)"}
        for field, header in (
            ("etag", "If-None-Match"),
            ("modified", "If-Modified-Since"),
        ):
            if old.get(field):
                headers[header] = old[field]
        for attempt in range(3):
            try:
                with urlopen(Request(url, headers=headers), timeout=12) as response:
                    if urlparse(response.url).hostname not in ALLOWED:
                        raise ValueError("Unexpected source redirect")
                    body = response.read(12_000_001)
                    if len(body) > 12_000_000:
                        raise ValueError("Oversized source")
                    self.used[url] = {
                        "body": base64.b64encode(body).decode(),
                        "etag": response.headers.get("ETag"),
                        "modified": response.headers.get("Last-Modified"),
                    }
                    return body
            except HTTPError as exc:
                if exc.code == 304 and old:
                    self.used[url] = old
                    return base64.b64decode(old["body"])
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
            except URLError, TimeoutError:
                if attempt == 2:
                    raise
            time.sleep(0.25 * 2**attempt)
        raise RuntimeError("Unreachable fetch failure")


def literal_array(script):
    match = re.search(r'\[\{category:["\'](?:OVAL|SPORTS CAR)', script)
    if not match:
        return None
    start = match.start()
    depth, quote, escaped = 0, None, False
    for index in range(start, len(script)):
        char = script[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth == 0:
                return json5.loads(script[start : index + 1])
    raise ValueError("Truncated Hub data")


def hub_series(fetch):
    html = BeautifulSoup(fetch.get(HUB), "html.parser")
    queue = [urljoin(HUB, s["src"]) for s in html.select('script[type="module"][src]')]
    seen = set()
    while queue and len(seen) < 6:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        script = fetch.get(url).decode()
        data = literal_array(script)
        if data is not None:
            validate_series(data)
            advertised = re.search(r"with (\d+) series", html.get_text(" ", strip=True))
            if not advertised or len(data) != int(advertised[1]):
                raise ValueError(
                    "Hub series count disagrees with its published inventory"
                )
            return [s | {"sources": [HUB]} for s in data]
        queue.extend(
            urljoin(url, path)
            for path in re.findall(r'from\s*["\'](\./[^"\']+\.js)["\']', script)
        )
    raise ValueError("Hub schedule literal not found")


def validate_series(data):
    if not isinstance(data, list) or len(data) < 80:
        raise ValueError("Incomplete series inventory")
    if not CATEGORIES <= {s["category"] for s in data}:
        raise ValueError("Missing racing categories")
    names = set()
    for series in data:
        if series["name"] in names or not series["weeks"]:
            raise ValueError("Duplicate series or missing rounds")
        names.add(series["name"])
        for key in ("name", "cars", "license", "frequency"):
            if not isinstance(series[key], str):
                raise TypeError(f"Invalid {key}")
        rounds = set()
        for rnd in series["weeks"]:
            date.fromisoformat(rnd["date"])
            if rnd["week"] in rounds or not rnd["track"] or not rnd["laps"]:
                raise ValueError("Incomplete/duplicate round")
            rounds.add(rnd["week"])


def official_series(body, hub):
    """Read layout columns; parentheses under Track are simulation conditions only."""
    reader = PdfReader(io.BytesIO(body))
    if len(reader.pages) < 50:
        raise ValueError("Truncated official season PDF")
    text = "\n".join(
        page.extract_text(extraction_mode="layout") for page in reader.pages
    )
    # Skip the table of contents, whose dotted leaders are not series headings.
    heading = re.compile(
        r"^[ \t]{0,2}((?:[^\n]+?20\d{2} Season(?: \d+)?[^\n]*?|20\d{2} [^\n]+?))\s*$",
        re.MULTILINE,
    )
    headings = [
        m for m in heading.finditer(text) if " . " not in m[1] and ".." not in m[1]
    ]
    blocks = {}
    for index, match in enumerate(headings):
        name = " ".join(match[1].split())
        block = text[
            match.end() : headings[index + 1].start()
            if index + 1 < len(headings)
            else len(text)
        ]
        blocks.setdefault(name, "")
        blocks[name] += "\n" + block
    hub = list(hub)
    known = {series["name"] for series in hub}
    for match in headings:
        name = " ".join(match[1].split())
        categories = re.findall(
            r"Class Series \((OVAL|SPORTS CAR|FORMULA CAR|DIRT OVAL|DIRT ROAD|UNRANKED)\)",
            text[: match.start()],
        )
        if name not in known and categories and categories[-1] in CATEGORIES:
            hub.append(
                {
                    "name": name,
                    "category": categories[-1],
                    "cars": "",
                    "license": "",
                    "frequency": "",
                    "weeks": [],
                    "sources": [PDF],
                }
            )
            known.add(name)
    result = []
    for series in hub:
        if series["category"] not in CATEGORIES:
            continue
        block = blocks.get(series["name"])
        if block is None:
            # Different season coverage must not erase data outside this document.
            result.append(series)
            continue
        lines = block.splitlines()
        frequency = next(
            (
                line.strip()
                for line in lines
                if re.match(
                    r"\s*(Races? |Every hour|\d+ Timeslots|Four timeslots|Fri at|Friday at|Open Qualifier)",
                    line,
                )
            ),
            None,
        )
        if frequency is None:
            raise ValueError(f"Missing official frequency: {series['name']}")
        week_matches = list(
            re.finditer(
                r"^\s*Week (\d+) \((\d{4}-\d{2}-\d{2})\)\s+([^\n]+)",
                block,
                re.MULTILINE,
            )
        )
        if not week_matches:
            raise ValueError("Official series has no rounds")
        weeks = []
        for index, match in enumerate(week_matches):
            section = block[
                match.start() : week_matches[index + 1].start()
                if index + 1 < len(week_matches)
                else len(block)
            ]
            columns = re.split(r"\s{2,}", match[3].strip())
            length = re.search(r"\b(\d+)\s+(laps|mins)\b", section)
            if not length:
                # Layout extraction may split the length value and unit across rows.
                length = re.search(r"\b(\d+)\s*\n\s+mins\b", section)
                race_length = length[1] + " mins" if length else None
                trailing = re.search(r"\b(\d+)\s*$", match[3])
                if (
                    not race_length
                    and trailing
                    and "mins" in " ".join(section.splitlines()[:3])
                ):
                    race_length = trailing[1] + " mins"
            else:
                race_length = f"{length[1]} {length[2]}"
            old = next((r for r in series["weeks"] if r["week"] == int(match[1])), None)
            if not race_length and not old:
                raise ValueError("Unrecognized race length")
            track = columns[0]
            track_column = match.start(3) - block.rfind("\n", 0, match.start(3)) - 1
            for continuation in section.splitlines()[1:]:
                track_part = re.split(r"\s{2,}", continuation[track_column:].strip())[0]
                if not track_part:
                    break
                if "(" in track_part:
                    prefix = track_part.split("(", 1)[0].strip()
                    track += (" " + prefix) if prefix else ""
                    break
                track += " " + track_part
            weeks.append(
                {
                    "week": int(match[1]),
                    "date": match[2],
                    "track": track,
                    "laps": race_length or old["laps"],
                }
            )
        license_line = next(
            (line.strip() for line in lines if "-->" in line), series["license"]
        )
        car_lines = []
        for line in lines:
            if "-->" in line:
                break
            if line.strip():
                car_lines.append(line.strip())
        result.append(
            series
            | {
                "frequency": frequency,
                "weeks": weeks,
                "license": license_line,
                "cars": " ".join(car_lines),
                "sources": [HUB, PDF],
            }
        )
    if sum(PDF in s["sources"] for s in result) < 60:
        raise ValueError("Official PDF series coverage incomplete")
    return result


# Explicit source-name mappings, independent of minor heading spelling differences.
WEEKLY_NAMES = {
    "NASCAR IRACING SERIES": (
        "NASCAR iRacing Series Fixed",
        "NASCAR iRacing Series Open",
    ),
    "IRACING GRAND PRIX TOUR": (
        "Formula A - Grand Prix Tour - Fixed",
        "iRacing Formula A - Grand Prix Tour",
    ),
    "NASCAR MODIFIED TOUR": ("NASCAR Modified Tour Fixed",),
    "SUPER LATE MODEL TOUR": ("Super Late Model Tour Fixed",),
    "VINTAGE GRAND PRIX TOUR": ("Vintage Grand Prix Tour",),
    "CREVENTIC ENDURANCE SERIES": ("Creventic Endurance Series",),
}


def weekly_overrides(body, url):
    soup = BeautifulSoup(body, "html.parser")
    title = soup.find("h1")
    if not title:
        raise ValueError("Weekly post title missing")
    title_text = title.get_text(" ", strip=True)
    dates = re.search(
        r"\| ([A-Za-z]+) (\d+)(?:st|nd|rd|th)? to .*?, (20\d{2})", title_text
    )
    if not dates:
        raise ValueError("Weekly coverage missing")
    start = (
        datetime.strptime(f"{dates[1]} {dates[2]} {dates[3]}", "%B %d %Y")
        .replace(tzinfo=UTC)
        .date()
    )
    coverage = week_start(start.isoformat()).isoformat()
    output = {}
    for heading in soup.find_all(["h3", "h4"]):
        names = WEEKLY_NAMES.get(heading.get_text(" ", strip=True).upper())
        if not names:
            continue
        parts = []
        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) in ("h2", "h3", "h4"):
                break
            if hasattr(sibling, "get_text"):
                parts.append(sibling.get_text(" ", strip=True))
        text = " ".join(parts)
        match = re.search(
            r"The races this week are scheduled for:\s*(.*?)\s*For more information",
            text,
        )
        if not match:
            raise ValueError(f"Missing weekly times: {names}")
        schedules = re.split(r"(?:Fixed|Open) Schedule\s*:\s*", match[1])
        schedules = [s.strip() for s in schedules if s.strip()]
        if len(schedules) != len(names):
            raise ValueError("Weekly setup schedules mismatch")
        for name, schedule in zip(names, schedules, strict=True):
            output[(name, coverage)] = (race_slots(schedule), url)
    if not output:
        raise ValueError("No recognized weekly schedules")
    return output


def parse_date(month, day, year):
    return (
        datetime.strptime(f"{month[:3]} {day} {year}", "%b %d %Y")
        .replace(tzinfo=UTC)
        .date()
    )


def special_events(body):
    soup = BeautifulSoup(body, "html.parser")
    events = []
    for section in soup.select("section[id]"):
        heading = section.find("h2")
        if not heading:
            continue
        paragraphs = [
            re.sub(r"(20\d)\s+(\d)\b", r"\1\2", p.get_text(" ", strip=True))
            for p in section.find_all("p")
        ]
        stamp = next(
            (
                p
                for p in paragraphs
                if re.fullmatch(
                    r"[A-Za-z]+ \d+(?:\s*[-–]\s*(?:[A-Za-z]+ )?\d+)?, 20\d{2}", p
                )
            ),
            None,
        )
        if not stamp:
            if any("TBD" in p for p in paragraphs):
                continue  # No published date exists to place on a calendar.
            if section.find(string=re.compile("Cars Competing")):
                raise ValueError(
                    f"Special event date not recognized: {heading.get_text()}"
                )
            continue
        match = re.fullmatch(
            r"([A-Za-z]+) (\d+)(?:\s*[-–]\s*(?:([A-Za-z]+) )?(\d+))?, (20\d{2})", stamp
        )
        first = parse_date(match[1], match[2], match[5])
        last = parse_date(match[3] or match[1], match[4] or match[2], match[5])
        desc = "\n".join(p for p in paragraphs if p != stamp)
        # This service covers paved disciplines, excluding dirt/off-road specials.
        if re.search(
            r"dirt track|dirt oval|rallycross|off-road|chili bowl|knoxville nationals",
            desc + heading.get_text(),
            re.IGNORECASE,
        ):
            continue
        track_link = section.select_one('a[href*="/tracks/"]')
        cars = section.find("summary")
        slug = re.sub(r"[^a-z0-9]+", "-", heading.get_text().lower()).strip("-")
        key = f"special:{first.year}:{slug}"
        events.append(
            {
                "id": key + "|0",
                "round_id": key,
                "coverage": f"special:{first.year}",
                "name": heading.get_text(" ", strip=True),
                "start": first.isoformat(),
                "end": (last + timedelta(days=1)).isoformat(),
                "all_day": True,
                "track": track_link.get_text(" ", strip=True) if track_link else "",
                "cars": cars.get_text(" ", strip=True) if cars else "",
                "length": (
                    re.search(r"\b(\d+)[ -]hour", desc, re.IGNORECASE)[1] + " hours"
                )
                if re.search(r"\b(\d+)[ -]hour", desc, re.IGNORECASE)
                else "",
                "eligibility": "",
                "description": desc,
                "sources": [SPECIAL + "#" + section["id"]],
            }
        )
    if len(events) < 10:
        raise ValueError("Special event coverage incomplete")
    return events


def extract(fetch, saved_overrides=None):
    hub = hub_series(fetch)
    series = official_series(fetch.get(PDF), hub)
    news = BeautifulSoup(fetch.get(NEWS), "html.parser")
    links = sorted(
        {
            urljoin(NEWS, a["href"])
            for a in news.select("a[href]")
            if "/this-week-in-iracing-" in a["href"]
        }
    )
    if not links:
        raise ValueError("Weekly source discovery failed")
    overrides = dict(saved_overrides or {})
    for url in links[:3]:
        overrides.update(weekly_overrides(fetch.get(url), url))
    events = [event for s in series for event in occurrences(s, overrides)]
    specials = special_events(fetch.get(SPECIAL))
    announcements = sorted(
        {
            urljoin(NEWS, a["href"])
            for a in news.select("a[href]")
            if "/this-week-iracing-" in a["href"] and "special-event" in a["href"]
        }
    )
    announcements = list(
        dict.fromkeys(
            announcements
            + [
                url
                for url in fetch.cache
                if "/this-week-iracing-" in url and "special-event" in url
            ]
        )
    )
    for url in announcements[:5]:
        special_starts(specials, fetch.get(url), url)
    events = deduplicate(events, specials)
    if not events:
        raise ValueError("Unexpected empty extraction")
    return events, sorted({e["coverage"] for e in events}), overrides


# Special events that are the same competition as championship rounds.
# Names, rather than page anchor IDs, are used: the official page reuses spa-24.
SPECIAL_ROUNDS = {
    "Daytona 500": ("NASCAR iRacing Series Fixed", "NASCAR iRacing Series Open"),
    "Coca-Cola 600": ("NASCAR iRacing Series Fixed", "NASCAR iRacing Series Open"),
    "Brickyard 400": ("NASCAR iRacing Series Fixed", "NASCAR iRacing Series Open"),
    "Southern 500": ("NASCAR iRacing Series Fixed", "NASCAR iRacing Series Open"),
    "Homestead Championship": (
        "NASCAR iRacing Series Fixed",
        "NASCAR iRacing Series Open",
    ),
    "Petit Le Mans": ("{year} Petit Le Mans Presented by VCO",),
    "Britcar 24HR": ("{year} Britcar 24 Presented by Cosworth",),
}


def deduplicate(events, specials):
    grouped = {}
    for special in specials:
        grouped.setdefault(special.get("round_id", special["name"]), []).append(special)
    for group in grouped.values():
        special = group[0]
        names = tuple(
            n.format(year=special["start"][:4])
            for n in SPECIAL_ROUNDS.get(special["name"], ())
        )
        matches = [
            e
            for e in events
            if e["name"] in names
            and week_start(e["start"][:10]) == week_start(special["start"][:10])
        ]
        if matches:
            for event in matches:
                event["description"] = special["name"] + "\n" + special["description"]
                event["sources"] = sorted(
                    set(event["sources"] + [url for e in group for url in e["sources"]])
                )
                if len(names) == 1:
                    event["round_id"] = special["round_id"]
                    event["id"] = (
                        special["round_id"] + "|" + event["id"].rsplit("|", 1)[1]
                    )
                    event["name"] = special["name"]
                    event["coverage"] = special["coverage"]
            continue
        events.extend(group)
    return events


def special_starts(specials, body, url):
    """Accept explicit numbered race slots, never the simulated date in the prose."""
    soup = BeautifulSoup(body, "html.parser")
    title = soup.find("h1")
    if not title:
        raise ValueError("Special announcement title missing")
    text = soup.get_text(" ", strip=True)
    title_text = title.get_text(" ", strip=True).lower()
    matches = [e for e in specials if e["name"].lower() in title_text]
    if len(matches) != 1:
        return
    event = matches[0]
    year = event["start"][:4]
    if not re.search(r"ABOUT THE " + year, text, re.IGNORECASE):
        return  # Reused URLs must explicitly identify the event year.
    slots = re.findall(
        r"Timeslot\s*#\d+:\s*((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) at \d{1,2}:\d{2} GMT)",
        text,
    )
    if not slots:
        if re.search(r"Timeslot\s*#", text):
            raise ValueError("Unrecognized special-event timeslots")
        return
    if len(slots) != len(re.findall(r"Timeslot\s*#\d+:", text)):
        raise ValueError("Incomplete special-event timeslots")
    timed = []
    for index, (day, hour, minute) in enumerate(race_slots(", ".join(slots))):
        first = date.fromisoformat(event["start"])
        when = first + timedelta(days=(day - first.weekday()) % 7)
        if when >= date.fromisoformat(event["end"]):
            raise ValueError("Special timeslot outside published dates")
        from datetime import UTC
        from datetime import time as wall_time

        start = datetime.combine(when, wall_time(hour, minute), UTC)
        timed.append(
            event
            | {
                "id": event["round_id"] + f"|{index}",
                "all_day": False,
                "start": start.isoformat(),
                "end": (
                    start + timedelta(hours=int(event["length"].split()[0]))
                ).isoformat()
                if event.get("length", "").endswith(" hours")
                else None,
                "sources": event["sources"] + [url],
            }
        )
    specials.remove(event)
    specials.extend(timed)
