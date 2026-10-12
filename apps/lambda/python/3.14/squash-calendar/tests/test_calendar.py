from datetime import UTC, datetime, timedelta

from icalendar import Calendar

from squash_calendar.calendar import description, reconcile, render
from squash_calendar.handlers import serve
from squash_calendar.source import season

NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)


def data(now=NOW):
    return {
        "as_of": now.isoformat(),
        "ratings": {p: 2.5 for p in season()["players"]},
        "matches": [],
        "names": {p: x["name"] for p, x in season()["players"].items()},
        "coverage": "Accessible results only",
        "backtest": {},
    }


def test_exact_pdf_fixtures_and_dst():
    events = Calendar.from_ical(render(reconcile({}, None, NOW), NOW)).walk("VEVENT")
    assert len(events) == 8
    assert [e.decoded("dtstart").strftime("%m-%d %H:%M") for e in events] == [
        "09-22 21:00",
        "10-06 21:00",
        "10-13 21:00",
        "10-20 21:00",
        "10-27 21:00",
        "11-17 22:00",
        "11-24 22:00",
        "12-01 22:00",
    ]
    assert [str(e["summary"]) for e in events] == [
        "Squash vs Meghan Churchill - Court 2",
        "Squash vs Katie Thompson - Court 2",
        "Squash vs Catherine Dale - Court 1",
        "Squash vs Alex Porter - Court 1",
        "Squash vs Meghan Churchill - Court 2",
        "Squash vs Katie Thompson - Court 2",
        "Squash vs Catherine Dale - Court 1",
        "Squash vs Alex Porter - Court 1",
    ]
    assert all(
        e.decoded("dtend") - e.decoded("dtstart") == timedelta(minutes=30)
        for e in events
    )
    assert all(str(e["transp"]) == "OPAQUE" and not e.walk("VALARM") for e in events)
    assert len({str(e["uid"]) for e in events}) == 8


def test_freeze_without_retrospective_predictions():
    events = reconcile({}, data(), NOW)
    keys = list(events)
    assert events[keys[0]]["preview"] is None
    old = events[keys[2]]["preview"]
    later = datetime(2026, 10, 14, 12, tzinfo=UTC)
    changed = data(later)
    changed["ratings"]["377557"] = 9
    after = reconcile(events, changed, later)
    assert after[keys[2]]["preview"] == old
    assert after[keys[3]]["preview"]["ratings"]["531624"] == 2.5
    assert "No retrospective" in description(after[keys[0]], later)


def test_revisions_move_cancel_restore_and_new_opponent():
    manifest = season()
    before = reconcile({}, data(), NOW, manifest)
    key = manifest["fixtures"][2]["id"]
    assert reconcile(before, data(), NOW, manifest) == before
    manifest["fixtures"][2]["date"] = "2026-10-14"
    after = reconcile(before, data(), NOW, manifest)
    assert after[key]["sequence"] == before[key]["sequence"] + 1
    fixture = manifest["fixtures"].pop(2)
    cancelled = reconcile(after, None, NOW, manifest)
    assert cancelled[key]["status"] == "CANCELLED"
    manifest["fixtures"].insert(2, fixture)
    restored = reconcile(cancelled, None, NOW, manifest)
    assert restored[key]["sequence"] == cancelled[key]["sequence"] + 1
    manifest["fixtures"][2]["opponent"] = "531624"
    assert reconcile(restored, None, NOW, manifest)[key]["preview"] is None


def test_result_requires_exact_player_pair_date_and_division():
    source = data()
    source["matches"] = [
        {
            "id": "1",
            "date": "2026-10-06",
            "division": 6498,
            "home": "491725",
            "away": "581919",
            "winner": "581919",
            "games": [[7, 11]] * 3,
        }
    ]
    result = reconcile({}, source, NOW)
    assert all(e["result"] is None for e in result.values())
    source["matches"][0]["away"] = "462638"
    source["matches"][0]["winner"] = "462638"
    result = reconcile({}, source, NOW)
    assert "Katie" in list(result.values())[1]["result"]


def test_staleness_etag_and_download():
    events = reconcile({}, data(), NOW)
    for item in events.values():
        if item["preview"]:
            item["preview"]["probability"] = 52
    snapshot = {"events": events}
    fresh = serve({}, snapshot, NOW)
    assert fresh["statusCode"] == 200 and "52%" in fresh["body"]
    assert "attachment" in fresh["headers"]["Content-Disposition"]
    assert (
        serve({"headers": {"If-None-Match": fresh["headers"]["ETag"]}}, snapshot, NOW)[
            "statusCode"
        ]
        == 304
    )
    stale = serve({}, snapshot, NOW + timedelta(hours=49))
    assert "(stale)" in stale["body"] and "suppressed" in stale["body"]
    assert stale["headers"]["ETag"] != fresh["headers"]["ETag"]
    assert serve({}, None, NOW)["statusCode"] == 503


def test_future_fixture_survives_outage_without_recomputing_old_preview():
    events = reconcile({}, data(), NOW)
    after = reconcile(events, None, NOW + timedelta(hours=1))
    assert events == after
