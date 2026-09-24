"""Read dated Paul Reynolds swimming sessions from the city's weekly calendar."""
from datetime import date, datetime, timedelta
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup
import httpx

from swim_calendar.source import ZONE, instant

BASE = "https://calendar.stjohns.ca"
# Verified with an A/B/A comparison in real Lambda: default httpx UA receives
# 403; this header receives complete HTML without cookies or JavaScript.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
CATEGORIES = {
    "6 Lane & Leisure": "Lane Swim",
    "3 Lane & Leisure": "Lane Swim",
    "6 Lane Swim": "Lane Swim",
    "Everyone Welcome Swim": "Open Swim",
    "Leisure Swim": "Leisure Swim",
    "Therapeutic Adult Swim": "Therapeutic Swim",
}


def weekly_events(html, week):
    """Reject wrong weeks, truncated pages and incomplete event markup."""
    if not re.search(r"</html\s*>\s*$", html, re.I):
        raise ValueError("Incomplete city calendar document")
    page = BeautifulSoup(html, "html.parser")
    if not any(h.get_text(strip=True) == "Paul Reynolds Community Centre" for h in page.find_all("h1")):
        raise ValueError("Wrong city calendar facility")
    for name, offset in (("PreviousWeek", -7), ("NextWeek", 7)):
        link = page.find("a", id=name)
        target = urlsplit(urljoin(BASE, link.get("href", ""))) if link else None
        expected = (week + timedelta(days=offset)).strftime("%m/%d/%Y")
        if (not target or target.netloc != "calendar.stjohns.ca" or target.path != "/prcc/Week"
                or parse_qs(target.query).get("StartDate") != [expected]):
            raise ValueError("Wrong or incomplete city calendar week")
    # The final hour cell must exist even on an empty/holiday week.
    if page.find(id="hour-48-day-0") is None:
        raise ValueError("Incomplete city calendar grid")
    links = page.select('a[href*="/Detail/"]')
    records = page.select(".day__event-meta")
    if len(links) != len(records):
        raise ValueError("Incomplete city calendar event collection")
    events, seen = [], set()
    for record in records:
        times, anchors = record.select(".calendar-bar-time"), record.select('a[href*="/Detail/"]')
        if len(times) != 1 or len(anchors) != 1:
            raise ValueError("Malformed city calendar event")
        anchor = anchors[0]
        path = anchor["href"]
        match = re.fullmatch(r"/prcc/Detail/(\d{4}-\d{2}-\d{2})-\d{4}-.+", path)
        if not match or path in seen:
            raise ValueError("Invalid or duplicate city occurrence identity")
        seen.add(path)
        day = date.fromisoformat(match[1])
        if not week <= day < week + timedelta(days=7):
            raise ValueError("City occurrence outside requested week")
        title = anchor.get_text(" ", strip=True)
        interval = re.fullmatch(r"(\d{1,2}:\d{2} [ap]m)\s*-\s*(\d{1,2}:\d{2} [ap]m)", times[0].get_text(strip=True), re.I)
        if interval is None:
            raise ValueError("Missing city occurrence duration")
        start, end = [instant(day, datetime.strptime(t.upper(), "%I:%M %p").time().isoformat())
                      for t in interval.groups()]
        if end <= start:
            raise ValueError("Invalid city occurrence duration")
        if re.search(r"cancelled|canceled|closed", title, re.I):
            continue
        category = CATEGORIES.get(title)
        if category is None:
            # Do not quietly drop a newly named swimming activity. Known child
            # and fitness sessions are intentionally excluded.
            if re.search(r"swim|lane|leisure", title, re.I):
                raise ValueError("Unrecognized city swimming activity")
            continue
        key = "city:prcc:" + path.rsplit("/", 1)[1]
        events.append(dict(id=key, start=start, end=end, title=f"{category}: {title}",
                           category=category, location="Paul Reynolds Community Centre - 35 Carrick Drive",
                           description="Published drop-in activity; not a reservation. Admission fees and "
                           "eligibility rules apply. Check the linked city listing for current details.",
                           url=BASE + path, status="active"))
    return events


class PaulReynolds:
    def __init__(self):
        self.client = httpx.Client(base_url=BASE, timeout=httpx.Timeout(20, connect=5),
                                   headers={"User-Agent": USER_AGENT, "Accept": "text/html"})

    def close(self):
        self.client.close()

    def collect(self, start, end, remaining=lambda: 600_000):
        week = start - timedelta(days=(start.weekday() + 1) % 7)
        collected = {}
        while week < end:
            if remaining() < 30_000:
                raise TimeoutError("Insufficient time to read city calendar")
            response = self.client.get("/prcc/Week", params={"StartDate": week.strftime("%m/%d/%Y")})
            response.raise_for_status()
            if "text/html" not in response.headers.get("content-type", ""):
                raise ValueError("Unexpected city calendar content type")
            for item in weekly_events(response.text, week):
                if start <= datetime.fromisoformat(item["start"]).astimezone(ZONE).date() < end:
                    if item["id"] in collected:
                        raise ValueError("Duplicate city occurrence")
                    collected[item["id"]] = item
            week += timedelta(days=7)
        return collected
