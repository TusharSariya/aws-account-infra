"""Year-scoped official inventory. Classification never infers API identity."""

import calendar
import json
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

SOURCE = "https://www.iracing.com/special-events/"
MONTHS = {
    name.lower(): i
    for i in range(1, 13)
    for name in (calendar.month_name[i], calendar.month_abbr[i])
}


def date_window(text, year):
    """Only observed, unambiguous English range formats; end is exclusive."""
    text = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
    if text == "Date : TBD":
        return None, None
    match = re.fullmatch(
        r"([A-Za-z]+) (\d{1,2})\s*[-–]\s*(?:([A-Za-z]+) )?(\d{1,2}), (\d{4})", text
    )
    if not match or int(match[5]) != year:
        raise ValueError(f"Unsupported official date format for {year}: {text}")
    try:
        start = date(year, MONTHS[match[1].lower()], int(match[2]))
        end = date(year, MONTHS[(match[3] or match[1]).lower()], int(match[4]))
    except ValueError, KeyError:
        raise ValueError(f"Invalid official date range: {text}") from None
    if not start <= end <= start + timedelta(days=31):
        raise ValueError(f"Invalid official date range: {text}")
    return start.isoformat(), (end + timedelta(days=1)).isoformat()


def parse_inventory(html, year):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one("h1.wp-block-post-title")
    if (
        title is None
        or title.get_text(" ", strip=True) != f"{year} Special Events Calendar"
    ):
        raise ValueError("Official special-events page title/year changed")
    headings = soup.select("div.wp-block-column > h2.has-studio-h-3-font-size")
    if not headings:
        raise ValueError("Official special-events card structure changed")
    entries = {}
    for heading in headings:
        name = heading.get_text(" ", strip=True)
        block = heading.parent
        paragraph = heading.find_next_sibling()
        if (
            paragraph is None
            or paragraph.name != "p"
            or block.select_one("details > summary") is None
        ):
            raise ValueError(f"Official special-events card changed: {name}")
        # Empty separator preserves dates with the year split across inline tags.
        start, end = date_window(paragraph.get_text("", strip=True), year)
        if name in entries:
            raise ValueError(f"Duplicate official special-event name: {name}")
        urls = {SOURCE}
        for anchor in block.select(".wp-block-button a[href]"):
            url = urljoin(SOURCE, anchor["href"])
            if urlparse(url).scheme == "https" and urlparse(url).hostname in {
                "www.iracing.com",
                "forums.iracing.com",
            }:
                urls.add(url)
        entries[name] = {
            "name": name,
            "start": start,
            "end": end,
            "source_urls": sorted(urls),
        }
    return entries


def load_catalog(year):
    path = Path(__file__).with_name("catalogs") / f"{year}.json"
    data = json.loads(path.read_text())
    if data["year"] != year:
        raise ValueError("Special-event catalog year mismatch")
    return data


def coverage_report(catalog, inventory):
    """All unresolved entries stay visible; disagreements prohibit publication."""
    reviewed = {e["name"]: e for e in catalog["events"]}
    report = {
        "new": sorted(inventory.keys() - reviewed.keys()),
        "missing": sorted(reviewed.keys() - inventory.keys()),
        "disagreements": [],
        "unresolved": [],
        "undated": [],
    }
    for name, entry in reviewed.items():
        if entry["discipline"] not in {"Oval", "Sports Car", "Formula Car"}:
            continue
        if not entry["api_mappings"]:
            report["unresolved"].append(name)
        if entry["start"] is None:
            report["undated"].append(name)
        if name in inventory and (entry["start"], entry["end"]) != (
            inventory[name]["start"],
            inventory[name]["end"],
        ):
            report["disagreements"].append(name)
    report["publication_ready"] = not any(
        report[k] for k in ("new", "missing", "disagreements", "unresolved")
    )
    return report
