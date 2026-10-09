"""Recognize named Zwift campaigns without including ordinary club rides."""

import re

# First-party campaign names and event tags; evidence in docs/zwift-api-contract.md.
# New campaigns need an explicit entry, rather than treating every series as special.
CAMPAIGNS = {
    "Tour of Watopia": (
        r"tour of watopia",
        r"tourofwatopia(?:20\d{2})?(?:ride|race|stage\d+)*",
    ),
    "Tour de Zwift": (
        r"tour de zwift",
        r"(?:tourdezwift|tdz)(?:20\d{2})?(?:ride|race|stage\d+)*",
    ),
    "Zwift Games": (r"zwift games", r"zwiftgames(?:20\d{2})?(?:stage\d+)?"),
    "Zwift Big Spin": (
        r"(?:the )?(?:zwift )?big spin",
        r"(?:zwift)?bigspin(?:20\d{2})?(?:stage\d+)?",
    ),
}


def campaign(event):
    series = event.get("eventSeries") or {}
    names = [
        event.get("name", ""),
        series.get("name", "") if isinstance(series, dict) else "",
    ]
    tags = event.get("tags") or []
    for title, (phrase, tag_pattern) in CAMPAIGNS.items():
        if any(
            re.search(r"\b" + phrase + r"\b", name, re.IGNORECASE)
            for name in names
            if isinstance(name, str)
        ):
            return title
        if any(
            re.fullmatch(tag_pattern, tag, re.IGNORECASE)
            for tag in tags
            if isinstance(tag, str)
        ):
            return title
    return None
