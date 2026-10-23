"""Identity behavior at the actual extraction and reconciliation seams."""

import copy
from datetime import timedelta

import pytest
from test_api import HTML, NOW, SEASONS

from iracing_calendar.adapter import normalize
from iracing_calendar.api import ContractError
from iracing_calendar.catalog import coverage_report, load_catalog, parse_inventory
from iracing_calendar.identity import IdentityResolver
from iracing_calendar.migration import differences, migrate
from iracing_calendar.reconcile import reconcile


def publish(catalog, html=HTML, previous=None, seasons=SEASONS):
    previous = previous or {}
    events, coverage, report = normalize(seasons, catalog, html, NOW)
    events, coverage, mapping = migrate(previous, events, coverage)
    result = reconcile(previous, events, coverage, NOW + timedelta(hours=6))
    result["uid_migration"] = mapping
    return result, report


def test_mountain_rename_and_display_changes_preserve_all_identities():
    catalog = load_catalog(2026)
    before, _ = publish(catalog)
    changed = HTML.replace("SFL Mountain Showdown", "Mountain Showdown")
    entry = next(
        e for e in catalog["events"] if e["id"] == "2026:sfl-mountain-showdown"
    )
    entry["name"] = "Sponsor presents Mountain Showdown"
    after, report = publish(catalog, changed, before)
    assert not report["identity_warnings"]
    diff = differences(before, after)
    assert not diff["added"] and not diff["removed"]
    assert len(diff["name_changes"]) == 1
    old = next(
        e for e in before["events"] if e["provenance"]["special_id"] == entry["id"]
    )
    new = next(e for e in after["events"] if e["id"] == old["id"])
    assert new["sequence"] == old["sequence"] + 1
    assert new["created"] == old["created"]


def test_unrecognized_card_retains_old_special_but_refreshes_api():
    catalog = load_catalog(2026)
    before, _ = publish(catalog)
    old = next(
        e
        for e in before["events"]
        if e["provenance"]["special_id"] == "2026:sfl-mountain-showdown"
    )
    # Reproduce the deployed year-wide coverage representation.
    old["coverage"] = "special:2026"
    seasons = copy.deepcopy(SEASONS)
    for season in seasons:
        for round_ in season["schedules"]:
            round_["series_name"] += " New Sponsor"
    changed = HTML.replace("SFL Mountain Showdown", "An unreviewed sponsor title")
    after, report = publish(catalog, changed, before, seasons)
    retained = next(e for e in after["events"] if e["id"] == old["id"])
    assert retained == old | {"coverage": "special:2026:sfl-mountain-showdown"}
    assert report["identity_warnings"]
    assert not differences(before, after)["removed"]
    assert any("New Sponsor" in e["name"] for e in after["events"])
    fresh, _ = publish(catalog, changed)
    assert not any(
        e["provenance"]["special_id"] == "2026:sfl-mountain-showdown"
        for e in fresh["events"]
    )


def test_resolved_date_conflict_remains_fatal():
    with pytest.raises(ContractError, match="date"):
        publish(
            load_catalog(2026),
            HTML.replace("November 13-15, 2026", "November 14-15, 2026"),
        )


def test_coverage_migration_alone_does_not_change_calendar():
    before, _ = publish(load_catalog(2026))
    for event in before["events"]:
        if not event.get("api_identity"):
            event["coverage"] = "special:2026"
    after, _ = publish(load_catalog(2026), previous=before)
    assert after["ics"] == before["ics"]
    assert after["etag"] == before["etag"]


def test_explicit_aliases_only_and_stable_forum_reference():
    catalog = load_catalog(2026)
    entry = catalog["events"][0]
    resolver = IdentityResolver(catalog)
    assert resolver.resolve("  BATHURST   1000  ")["id"] == entry["id"]
    assert (
        resolver.resolve(
            "Entirely new sponsorship",
            ["https://forums.iracing.com/discussion/100630/new-sponsor-slug/p2/"],
        )["id"]
        == entry["id"]
    )
    assert (
        resolver.resolve("Entirely new sponsorship", [catalog["source"]])["id"] is None
    )
    entry["name"] = "Unregistered display label"
    resolver = IdentityResolver(catalog)
    assert resolver.resolve(entry["name"])["id"] is None
    assert resolver.resolve("Bathurst 1000")["id"] == entry["id"]
    conflict = resolver.resolve("Daytona 500", entry["source_urls"])
    assert conflict["status"] == "ambiguous"
    assert len(conflict["candidates"]) == 2


@pytest.mark.parametrize("field", ["id", "aliases"])
def test_conflicting_catalog_registrations_fail(field):
    catalog = load_catalog(2026)
    catalog["events"][1][field] = catalog["events"][0][field]
    with pytest.raises(ContractError):
        IdentityResolver(catalog)


def test_alias_phrase_boundaries_and_ambiguous_announcements():
    catalog = load_catalog(2026)
    resolver = IdentityResolver(catalog)
    assert (
        resolver.resolve("Preview: Bathurst 1000 sponsored by Example", phrase=True)[
            "id"
        ]
        == "2026:bathurst-1000"
    )
    assert resolver.resolve("Bathurst 10000", phrase=True)["id"] is None
    assert (
        resolver.resolve("Bathurst 1000 and Daytona 500", phrase=True)["status"]
        == "ambiguous"
    )
    catalog["events"][1]["aliases"].append("Bathurst")
    assert (
        IdentityResolver(catalog).resolve("Bathurst 1000", phrase=True)["status"]
        == "ambiguous"
    )


def test_duplicate_labels_do_not_merge_distinct_references_and_duplicate_cards_warn():
    catalog = load_catalog(2026)
    cards = parse_inventory(HTML, 2026)
    referenced = [c for c in cards if len(c["source_urls"]) > 1][:2]
    for card in referenced:
        card["name"] = "Shared sponsor display text"
    report = coverage_report(catalog, cards)
    assert not report["identity_warnings"]
    cards.append(copy.deepcopy(cards[0]))
    report = coverage_report(catalog, cards)
    assert any(w["status"] == "duplicate_card" for w in report["identity_warnings"])
    assert "2026:bathurst-1000" not in {m["id"] for m in report["inventory_matches"]}


def test_api_rename_keeps_uids_and_reports_only_names():
    catalog = load_catalog(2026)
    before, _ = publish(catalog)
    seasons = copy.deepcopy(SEASONS)
    for season in seasons:
        for round_ in season["schedules"]:
            round_["series_name"] += " Sponsor"
    after, _ = publish(catalog, previous=before, seasons=seasons)
    delta = differences(before, after)
    assert delta["name_changes"]
    assert not any(
        delta[k] for k in ["added", "removed", "start_changes", "end_changes"]
    )
    same, _ = publish(catalog, previous=after, seasons=seasons)
    assert same["ics"] == after["ics"]


@pytest.mark.parametrize(
    "title", ["Unknown Sponsor Festival", "Mountain Showdown and Daytona 500"]
)
def test_announcement_identity_warning_preserves_previously_confirmed_times(title):
    from iracing_calendar.adapter import extract
    from iracing_calendar.sources import NEWS

    url = "https://www.iracing.com/this-week-iracing-mountain-special-event/"

    class API:
        def get(self, endpoint, **params):
            return SEASONS if endpoint == "series/seasons" else []

    class Web:
        heading = "Mountain Showdown"

        def __init__(self):
            self.cache = {}

        def get(self, address):
            if address == NEWS:
                return f'<a href="{url}">Special event</a>'
            if address == url:
                return f'<div class="page-header"><h1>{self.heading}</h1></div><p>ABOUT THE 2026 EVENT</p><ul><li>Timeslot #1: Friday at 22:00 GMT</li></ul>'
            return HTML

    web = Web()
    catalog = load_catalog(2026)
    events, coverage, _ = extract(API(), catalog, web, NOW)
    before = reconcile({}, events, coverage, NOW)
    special = next(
        e
        for e in before["events"]
        if e["provenance"]["special_id"] == "2026:sfl-mountain-showdown"
    )
    assert not special["all_day"]
    web.heading = title
    events, coverage, report = extract(API(), catalog, web, NOW, before)
    after = reconcile(before, events, coverage, NOW + timedelta(hours=6))
    assert next(e for e in after["events"] if e["id"] == special["id"]) == special
    assert special["id"] in after["report"]["retained_unverified_ids"]
    assert any(
        w["status"] == "unverified_announcement" for w in report["identity_warnings"]
    )


def test_unknown_inventory_retention_still_expires():
    before, _ = publish(load_catalog(2026))
    changed = HTML.replace("SFL Mountain Showdown", "Unreviewed")
    events, coverage, _ = normalize(SEASONS, load_catalog(2026), changed, NOW)
    after = reconcile(before, events, coverage, NOW + timedelta(days=120))
    assert not any(
        e["provenance"]["special_id"] == "2026:sfl-mountain-showdown"
        for e in after["events"]
    )


def test_archived_season_discovery_ignores_mutable_short_name():
    from iracing_calendar.adapter import extract
    from iracing_calendar.sources import NEWS

    archived = next(s for s in SEASONS if s["season_id"] == 6216)
    calls = []

    class API:
        def get(self, endpoint, **params):
            if endpoint == "series/seasons":
                return [s for s in SEASONS if s["season_id"] != 6216]
            if endpoint == "series/stats_series":
                return [
                    {
                        "seasons": [
                            archived | {"season_short_name": "Renamed by Sponsor"}
                        ]
                    }
                ]
            calls.append(params["season_id"])
            return {
                "success": True,
                "season_id": 6216,
                "schedules": archived["schedules"],
            }

    class Web:
        def __init__(self):
            self.cache = {}

        def get(self, url):
            return (
                '<a href="https://www.iracing.com/">News</a>' if url == NEWS else HTML
            )

    extract(API(), load_catalog(2026), Web(), NOW)
    assert calls == [6216]


def test_reviewed_announcement_url_resolves_unrecognized_title_after_index_rollover():
    from iracing_calendar.announcements import supplement
    from iracing_calendar.sources import NEWS

    catalog = load_catalog(2026)
    entry = next(
        e for e in catalog["events"] if e["id"] == "2026:sfl-mountain-showdown"
    )
    url = "https://www.iracing.com/reviewed-announcement/"
    entry["source_urls"].append(url)
    events, _, _ = normalize(SEASONS, catalog, HTML, NOW)

    class Web:
        def __init__(self):
            self.cache = {}

        def get(self, address):
            if address == NEWS:
                return '<a href="https://www.iracing.com/">News</a>'
            assert address == url
            return '<div class="page-header"><h1>Brand New Sponsor</h1></div><p>ABOUT THE 2026 EVENT</p><ul><li>Timeslot #1: Friday at 22:00 GMT</li></ul>'

    warnings = []
    assert supplement(events, catalog, Web(), NOW, warnings) == [url]
    assert not warnings
    event = next(e for e in events if e["provenance"]["special_id"] == entry["id"])
    assert event["start"] == "2026-11-13T22:00:00+00:00"
