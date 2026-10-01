import copy
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError

import pytest

from iracing_calendar.adapter import normalize, starts
from iracing_calendar.api import ContractError, DataAPI
from iracing_calendar.catalog import load_catalog

FIXTURES = Path(__file__).with_name("fixtures")
SEASONS = json.loads((FIXTURES / "api/active-seasons.json").read_text()) + json.loads(
    (FIXTURES / "api/archived-seasons.json").read_text()
)
HTML = (FIXTURES / "special-events-2026.html").read_text()
NOW = datetime(2026, 10, 1, tzinfo=UTC)


def test_captured_api_inventory_specials_and_bristol():
    events, _, report = normalize(SEASONS, load_catalog(2026), HTML, NOW)
    assert report["publication_ready"]
    assert report["undated"] == ["Dale Jr Charity Event"]
    bristol = [
        e
        for e in events
        if "Bristol" in e["track"] and e["api_identity"]["series_id"] in (207, 229)
    ]
    assert bristol and all(
        e["length"] == "250 laps"
        and "special" not in e["classification"]
        and e["end"] is None
        for e in bristol
    )
    daytona = [e for e in events if e["provenance"]["special_id"] == "2026:daytona-500"]
    assert len(daytona) == 9
    assert {e["api_identity"]["fixed_setup"] for e in daytona} == {False, True}
    assert all(e["api_identity"]["race_week_num"] == 0 for e in daytona)
    petit = [e for e in events if e["provenance"]["special_id"] == "2026:petit-le-mans"]
    assert len(petit) == 5 and petit[0]["start"].startswith("2026-09-25")
    assert not any(e["start"].startswith("2026-10-03T10:55") for e in petit)
    assert len({(e["round_id"], e["start"]) for e in events}) == len(events)
    assert any("full_length_tour" in e["classification"] for e in events)


def test_round_dates_alternating_and_dst_are_not_extrapolated():
    season = next(s for s in SEASONS if s["season_id"] == 6465)
    values = [value for r in season["schedules"] for value in starts(r)]
    assert len(values) == 24
    assert datetime(2026, 9, 27, 0, tzinfo=UTC) in values
    assert not any(t.date().isoformat() == "2026-10-03" for t in values)
    # Actual explicit UTC starts either side of DST retain API authority.
    tour = next(s for s in SEASONS if s["season_id"] == 6081)
    assert all(
        starts(r)
        == sorted(
            datetime.fromisoformat(t)
            for d in r["race_time_descriptors"]
            for t in d["session_times"]
        )
        for r in tour["schedules"]
    )


def test_recurrence_only_inside_explicit_days_and_round_bounds():
    r = {
        "start_date": "2026-11-01",
        "week_end_time": "2026-11-02T00:30:00Z",
        "race_time_descriptors": [
            {
                "repeating": True,
                "start_date": "2026-11-01",
                "day_offset": [0, 1],
                "first_session_time": "00:15:00",
                "repeat_minutes": 60,
                "end_offset_minutes": 1439,
            }
        ],
    }
    assert starts(r) == []
    times = starts(r, include_repeating=True)
    assert len(times) == 25 and times[-1] == datetime(2026, 11, 2, 0, 15, tzinfo=UTC)
    r["race_time_descriptors"][0]["timezone"] = "America/New_York"
    with pytest.raises(ContractError, match="timezone"):
        starts(r, True)


def test_ambiguous_mapping_and_conflicting_track_block_publication():
    cat = load_catalog(2026)
    target = next(e for e in cat["events"] if e["name"] == "Daytona 500")
    target["api_mappings"][0]["track_id"] = -1
    with pytest.raises(ContractError, match="track/setup"):
        normalize(SEASONS, cat, HTML, NOW)
    cat = load_catalog(2026)
    target = next(e for e in cat["events"] if e["name"] == "Daytona 500")
    target["api_mappings"].append(copy.deepcopy(target["api_mappings"][0]))
    with pytest.raises(ContractError, match="Ambiguous"):
        normalize(SEASONS, cat, HTML, NOW)


class Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(json.dumps(response).encode())


def test_bearer_only_to_api_and_cached_download():
    opener = Opener(
        [
            {"link": "https://scorpio-assets.s3.us-east-1.amazonaws.com/data.json"},
            [{"season_id": 42}],
        ]
    )
    api = DataAPI("not-a-real-token", opener=opener, clock=lambda: 0)
    assert api.get("series/seasons") == [{"season_id": 42}]
    assert opener.calls[0].get_header("Authorization") == "Bearer not-a-real-token"
    assert opener.calls[1].get_header("Authorization") is None
    cached = DataAPI("other", api.used, opener=Opener([]), clock=lambda: 1)
    assert cached.get("series/seasons") == [{"season_id": 42}]


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.invalid/data",
        "http://scorpio-assets.s3.amazonaws.com/data",
        "https://user@scorpio-assets.s3.amazonaws.com/data",
    ],
)
def test_untrusted_downloads_fail_without_sending_credentials(url):
    opener = Opener([{"link": url}])
    with pytest.raises(ContractError):
        DataAPI("secret", opener=opener).get("series/seasons")
    assert len(opener.calls) == 1


def test_rate_limit_bounded_retry_and_unknown_pagination():
    delays = []
    error = HTTPError(
        "https://members-ng.iracing.com", 429, "", {"Retry-After": "2"}, None
    )
    api = DataAPI("secret", opener=Opener([error, []]), sleep=delays.append)
    assert api.get("series/seasons") == [] and delays == [2]
    with pytest.raises(ContractError, match="pagination"):
        DataAPI("secret", opener=Opener([{"next_page": 2}])).get("series/seasons")


def test_incomplete_chunks_fail_closed():
    opener = Opener(
        [
            {
                "chunk_info": {
                    "base_download_url": "https://scorpio-assets.s3.amazonaws.com/",
                    "chunk_file_names": ["a.json"],
                    "num_results": 2,
                }
            },
            [1],
        ]
    )
    with pytest.raises(ContractError, match="Incomplete"):
        DataAPI("secret", opener=opener).get("series/seasons")


def test_announcement_fixture_and_api_disagreement():
    from iracing_calendar.announcements import announcement_starts, supplement
    from iracing_calendar.sources import NEWS

    cat = load_catalog(2026)
    body = (FIXTURES / "announcement-bathurst-2026.html").read_text()
    entry = next(e for e in cat["events"] if e["name"] == "Bathurst 1000")
    expected = announcement_starts(body, entry, 2026)
    assert len(expected) == 5 and expected[0] == "2026-10-03T03:00:00+00:00"
    assert announcement_starts(body, entry, 2025) is None
    with pytest.raises(ContractError):
        announcement_starts(body.replace("Saturday at 03:00 GMT", "TBD"), entry, 2026)
    url = "https://www.iracing.com/this-week-iracing-bathurst-special-event/"

    class Fetch:
        def __init__(self):
            self.cache = {url: {}}

        def get(self, address):
            return (
                '<a href="https://www.iracing.com/">News</a>'
                if address == NEWS
                else body
            )

    events, _, _ = normalize(SEASONS, cat, HTML, NOW)
    assert supplement(events, cat, Fetch(), NOW) == [url]
    race = next(
        e for e in events if e.get("provenance", {}).get("special_id") == entry["id"]
    )
    race["start"] = "2026-10-03T04:00:00+00:00"
    with pytest.raises(ContractError, match="exact-start conflict"):
        supplement(events, cat, Fetch(), NOW)


def test_real_uid_migration_corrections_and_idempotent_refresh():
    from iracing_calendar.migration import migrate
    from iracing_calendar.reconcile import reconcile

    legacy = json.loads((FIXTURES / "api/legacy-events.json").read_text())
    previous = {"events": legacy}
    incoming, coverage, _ = normalize(SEASONS, load_catalog(2026), HTML, NOW)
    incoming, coverage, mapping = migrate(previous, incoming, coverage)
    result = reconcile(previous, incoming, coverage, NOW)
    result["uid_migration"] = mapping
    by_id = {e["id"]: e for e in result["events"]}
    for old in legacy:
        assert old["id"] in by_id
        assert by_id[old["id"]]["sequence"] > old["sequence"]
        assert by_id[old["id"]]["created"] == old["created"]
    incoming, coverage, _ = normalize(SEASONS, load_catalog(2026), HTML, NOW)
    incoming, coverage, persisted = migrate(result, incoming, coverage)
    assert persisted == mapping
    again = reconcile(result, incoming, coverage, NOW)
    assert again["ics"] == result["ics"]
    # Removed starts cancel only inside the explicitly covered API season.
    sid = legacy[0]["id"]
    removed = [e for e in incoming if e["round_id"] != by_id[sid]["round_id"]]
    cancelled = reconcile(result, removed, coverage, NOW)
    assert sid not in {e["id"] for e in cancelled["events"]}


def test_completed_races_confirm_all_reviewed_timed_corrections():
    proof = json.loads((FIXTURES / "api/completed-starts.json").read_text())
    mapping = json.loads(Path("iracing_calendar/catalogs/migration.json").read_text())
    confirmed = {datetime.fromisoformat(t) for rows in proof.values() for t in rows}
    assert len(mapping["reviewed_start_corrections"]) == 7
    assert all(
        datetime.fromisoformat(c["after"]) in confirmed
        for c in mapping["reviewed_start_corrections"]
    )
