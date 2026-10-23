"""Deterministic official announcements supplement dates; exact conflicts stop sync."""

import re
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .api import ContractError
from .duration import end_time
from .identity import IdentityResolver, source_reference
from .sources import NEWS

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def announcement_starts(body, entry, year):
    soup = BeautifulSoup(body, "html.parser")
    heading = soup.select_one("div.page-header > h1")
    if heading is None:
        raise ContractError("Official announcement heading structure changed")
    text = soup.get_text(" ", strip=True)
    if not re.search(rf"ABOUT THE {year}\b", text):
        return None
    slots = [
        node.get_text(" ", strip=True)
        for node in soup.select("li")
        if "Timeslot #" in node.get_text()
    ]
    if text.count("Timeslot #") != len(slots):
        raise ContractError("Unsupported announcement timeslot structure")
    values = []
    for slot in slots:
        match = re.match(
            r"Timeslot #(\d+): (Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) at (\d{1,2}):(\d{2}) GMT(?:\b|$)",
            slot,
        )
        if match is None or int(match[1]) != len(values) + 1 or not entry["start"]:
            raise ContractError("Malformed or undated official timeslot")
        first = date.fromisoformat(entry["start"])
        day = first + timedelta(days=(DAYS.index(match[2]) - first.weekday()) % 7)
        if day >= date.fromisoformat(entry["end"]):
            raise ContractError("Official timeslot outside catalog date window")
        values.append(
            datetime.combine(day, time(int(match[3]), int(match[4])), UTC).isoformat()
        )
    return values


def supplement(events, catalog, fetch, now, warnings=None):
    warnings = warnings if warnings is not None else []
    resolver = IdentityResolver(catalog)
    news = BeautifulSoup(fetch.get(NEWS), "html.parser")
    urls = {urljoin(NEWS, a["href"]) for a in news.select("a[href]")}
    urls.update(fetch.cache)
    reviewed_articles = {
        url
        for entry in catalog["events"]
        for url in entry["source_urls"]
        if urlsplit(url).hostname == "www.iracing.com" and source_reference(url)
    }
    urls.update(reviewed_articles)
    urls = sorted(
        url
        for url in urls
        if urlsplit(url).hostname == "www.iracing.com"
        and (
            url in reviewed_articles
            or ("/this-week-iracing-" in url and "special-event" in url)
        )
    )
    if not news.select("a[href]"):
        raise ContractError("Official news index structure changed")
    checked = []
    for url in urls:
        body = fetch.get(url)
        soup = BeautifulSoup(body, "html.parser")
        heading = soup.select_one("div.page-header > h1")
        if heading is None:
            raise ContractError("Official announcement heading structure changed")
        if not re.search(
            rf"ABOUT THE {catalog['year']}\b", soup.get_text(" ", strip=True)
        ):
            continue
        resolution = resolver.resolve(
            heading.get_text(" ", strip=True), [url], phrase=True
        )
        if resolution["id"] is None:
            warnings.append(resolution | {"source_kind": "announcement"})
            continue
        entry = resolver.entries[resolution["id"]]
        if entry["discipline"] not in {"Oval", "Sports Car", "Formula Car"}:
            continue
        published = announcement_starts(body, entry, catalog["year"])
        if published is None:
            continue
        checked.append(url)
        if not published:
            continue
        matches = [
            e
            for e in events
            if e.get("provenance", {}).get("special_id") == entry["id"]
        ]
        api_times = {e["start"] for e in matches if not e["all_day"]}
        if api_times and api_times != set(published):
            raise ContractError(
                f"API/announcement exact-start conflict: {entry['name']} ({url})"
            )
        if api_times:
            for event in matches:
                event["sources"] = sorted(set(event["sources"]) | {url})
        elif matches:
            if len(matches) != 1:
                raise ContractError("Ambiguous special date placeholders")
            placeholder = matches[0]
            events.remove(placeholder)
            events.extend(
                placeholder
                | {
                    "id": placeholder["round_id"] + f"|{i}",
                    "start": start,
                    "all_day": False,
                    "end": end_time(start, placeholder.get("duration")),
                    "sources": sorted(set(placeholder["sources"]) | {url}),
                    "provenance": placeholder["provenance"] | {"starts": url},
                }
                for i, start in enumerate(published)
            )
    return sorted(set(checked))
