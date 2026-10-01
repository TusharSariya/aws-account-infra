from pathlib import Path

import pytest

from iracing_calendar.catalog import (
    coverage_report,
    date_window,
    load_catalog,
    parse_inventory,
)

HTML = (
    Path(__file__)
    .with_name("fixtures")
    .joinpath("special-events-2026.html")
    .read_text()
)


def test_complete_reviewed_inventory_and_all_five_nascar_rounds():
    inventory = parse_inventory(HTML, 2026)
    catalog = load_catalog(2026)
    assert len(inventory) == 33
    paved = [
        e for e in catalog["events"] if e["discipline"] != "Excluded dirt/off-road"
    ]
    assert len(paved) == 30
    nascar = {
        e["name"] for e in paved if e["applicable_series"] == ["NASCAR iRacing Series"]
    }
    assert nascar == {
        "Daytona 500",
        "World 600",
        "Brickyard 400",
        "Southern 500",
        "Homestead Championship",
    }
    assert not any("Bristol" in e["name"] for e in catalog["events"])
    report = coverage_report(catalog, inventory)
    assert not report["publication_ready"]
    assert len(report["unresolved"]) == 8
    assert report["undated"] == ["Dale Jr Charity Event"]
    assert not report["new"] and not report["missing"] and not report["disagreements"]
    assert inventory["Daytona 500"]["start"] == "2026-02-11"


def test_official_detail_urls_retained_in_reviewed_catalog():
    catalog = load_catalog(2026)
    assert any(
        "forums.iracing.com" in url
        for event in catalog["events"]
        for url in event["source_urls"]
    )
    changed = parse_inventory(
        HTML.replace(
            'href="https://forums.iracing.com/', 'href="https://example.invalid/'
        ),
        2026,
    )
    # A rolling news/page index cannot erase the reviewed detail URLs.
    assert not coverage_report(catalog, changed)["missing"]
    assert any(
        "forums.iracing.com" in url
        for event in catalog["events"]
        for url in event["source_urls"]
    )


@pytest.mark.parametrize(
    "text,start,end",
    [
        ("Oct 30-31, 2026", "2026-10-30", "2026-11-01"),
        ("June 30 – July 6, 2026", "2026-06-30", "2026-07-07"),
        ("November 27–29, 2026", "2026-11-27", "2026-11-30"),
        ("Date : TBD", None, None),
    ],
)
def test_validated_date_formats(text, start, end):
    assert date_window(text, 2026) == (start, end)


@pytest.mark.parametrize(
    "text",
    [
        "Oct 31-30, 2026",
        "February 29-30, 2026",
        "June 1-2, 2025",
        "10/11/26",
        "Soon",
        "June 1 – September 1, 2026",
    ],
)
def test_reject_unknown_or_invalid_dates(text):
    with pytest.raises(ValueError):
        date_window(text, 2026)


@pytest.mark.parametrize(
    "html",
    [
        "<html>blocked</html>",
        HTML.replace("has-studio-h-3-font-size", "unknown"),
        HTML.replace("October 2-4, 2026", "unpublished format"),
        HTML.replace("2026 Special Events Calendar", "2027 Special Events Calendar"),
    ],
)
def test_unrecognized_page_structure_fails_closed(html):
    with pytest.raises(ValueError):
        parse_inventory(html, 2026)


def test_changed_names_dates_and_missing_cards_reported():
    inventory = parse_inventory(HTML, 2026)
    inventory["Daytona 500"]["start"] = "2026-02-12"
    inventory["Renamed Event"] = inventory.pop("Bathurst 1000")
    report = coverage_report(load_catalog(2026), inventory)
    assert report["disagreements"] == ["Daytona 500"]
    assert report["new"] == ["Renamed Event"]
    assert report["missing"] == ["Bathurst 1000"]
    assert not report["publication_ready"]
