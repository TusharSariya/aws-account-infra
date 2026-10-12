from datetime import UTC, datetime

import httpx
import pytest

from squash_calendar.source import ClubLocker, SourceError, normalize


def row():
    return {
        "id": 1,
        "status": "C",
        "SportID": 3,
        "EventName": "Singles",
        "winner": "V",
        "wid1": 462638,
        "oid1": 237203,
        "wid2": 0,
        "oid2": 0,
        "wset1": 11,
        "oset1": 5,
        "wset2": 13,
        "oset2": 15,
        "wset3": 11,
        "oset3": 7,
        "wset4": 11,
        "oset4": 4,
    }


def test_away_winner_is_not_reversed():
    m = normalize(row(), {"id": 253524, "date": "2026-09-22", "division": 6498})
    assert m["winner"] == "462638"
    assert m["games"] == [(11, 5), (13, 15), (11, 7), (11, 4)]


@pytest.mark.parametrize(
    "change",
    [
        {"status": "RE"},
        {"status": "DF"},
        {"status": "NP"},
        {"wid2": 42},
        {"winner": None},
        {"SportID": 2},
        {"wset1": 0},
        {"EventName": "Doubles"},
        {"oset4": 12},
        {"wset5": 11, "oset5": 5},
    ],
)
def test_exclusions(change):
    r = row()
    r.update(change)
    assert normalize(r, {"id": 1, "date": "2026-09-22", "division": 6498}) is None


def test_auth_failure_is_not_retried_or_bypassed():
    calls = []

    def route(request):
        calls.append(request.url)
        return httpx.Response(403, json={"private": "not logged"})

    client = ClubLocker(httpx.Client(transport=httpx.MockTransport(route)))
    with pytest.raises(SourceError, match="access unavailable"):
        client.rows("teams/49982/players")
    assert len(calls) == 1


def test_pinned_identity_mismatch_fails_closed():
    client = ClubLocker(
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
        )
    )
    with pytest.raises(SourceError, match="identity changed"):
        client.collect(datetime.now(UTC))


def test_unexpected_schema_fails_closed():
    client = ClubLocker(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"login": "required"})
            )
        )
    )
    with pytest.raises(SourceError, match="schema"):
        client.rows("test")


def test_collect_deduplicates_and_sanitizes_public_data():
    from squash_calendar.source import season

    manifest = season()
    manifest["seasons"] = [2616]
    roster = {
        str(p["team"]): {
            "playerid": int(pid),
            "player": p["roster_name"],
            "teamid": p["team"],
            "TeamPosition": "6",
            "secret": "never retain",
        }
        for pid, p in manifest["players"].items()
    }

    def route(request):
        path = request.url.path.removeprefix("/resources/")
        if path.startswith("teams/"):
            value = [roster[path.split("/")[1]]]
        elif path.endswith("/ratings"):
            value = [
                {"sportId": 3, "ratingTypeId": 1, "rating": 2.5},
                {"sportId": 1, "ratingTypeId": 1, "rating": 9},
            ]
        elif path == "leagues/info/2616":
            value = [
                {"OrganizationID": 10234, "SeasonDescr": "ASC Fall", "Leagueid": 6498}
            ]
        elif path.startswith("divisions/playerStandings"):
            value = []
        elif path.startswith("divisions/schedule"):
            value = [
                {
                    "matchdate": "09/22/26",
                    "Score_Entered": "Confirmed",
                    "scorecardid": 253524,
                }
            ] * 2
        elif path.endswith("/list"):
            value = [row(), row()]
        else:
            raise AssertionError(path)
        return httpx.Response(200, json=value)

    client = ClubLocker(httpx.Client(transport=httpx.MockTransport(route)))
    result = client.collect(datetime(2026, 10, 12, tzinfo=UTC), manifest=manifest)
    assert sum(m["id"] == "1" for m in result["matches"]) == 1
    assert result["ratings"]["491725"] == 2.5
    assert "secret" not in str(result)
