"""Exercise subscriber polls through real repository/reconciliation boundaries."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from booker.calendar_feed import serve
from booker.calendar_reconcile import reconcile
from booker.http import HeldReservation
from icalendar import Calendar
from moto import mock_aws
from test_calendar_storage import make_repo


@mock_aws
def test_manual_reservations_background_polls_and_revocation(monkeypatch):
    now = datetime(2026, 9, 23, 12, tzinfo=UTC)
    repo = make_repo()
    owner = repo.create_subscription("owner")
    friend = repo.create_subscription("friend")
    requests = []
    monkeypatch.setenv("CALENDAR_RECONCILE_FUNCTION", "synthetic-reconciler")

    def invoke(**kwargs):
        requests.append(json.loads(kwargs["Payload"]))
        return {"StatusCode": 202}

    client = SimpleNamespace(invoke=invoke)
    config = SimpleNamespace(
        timezone="America/St_Johns",
        equipment_ids={"court1": 7412, "court2": 12739},
        activity_label=lambda key: {"court1": "Court 1", "court2": "Court 2"}[key],
        visibility_for=lambda *_: ("public", None),
    )
    rows = [
        HeldReservation(501, 7412, None, "2026-09-24 17:00:00", "2026-09-24 18:30:00")
    ]
    upstream = SimpleNamespace(login=lambda *_: None, reservations=lambda *_: rows)
    credentials = SimpleNamespace(username="fixture", password="fixture")
    request = {"pathParameters": {"token": owner["token"]}}
    assert serve(request, repo, client, now)["statusCode"] == 503
    # Multiple subscribers share a single refresh lease.
    assert (
        serve({"pathParameters": {"token": friend["token"]}}, repo, client, now)[
            "statusCode"
        ]
        == 503
    )
    assert len(requests) == 1
    reconcile(repo, upstream, config, credentials, requests.pop()["lease_id"], now=now)
    response = serve(request, repo, client, now)
    assert response["statusCode"] == 200
    event = Calendar.from_ical(response["body"]).walk("VEVENT")[0]
    assert event.decoded("dtstart") == datetime(2026, 9, 24, 19, 30, tzinfo=UTC)
    assert event.decoded("dtend") == datetime(2026, 9, 24, 21, tzinfo=UTC)
    request["headers"] = {"If-None-Match": response["headers"]["ETag"]}
    later = now + timedelta(minutes=15)
    assert serve(request, repo, client, later)["statusCode"] == 304
    assert len(requests) == 1
    rows.clear()  # Synthetic external cancellation: never call reserve/cancel APIs.
    reconcile(
        repo, upstream, config, credentials, requests.pop()["lease_id"], now=later
    )
    response = serve(request, repo, client, later)
    assert response["statusCode"] == 200
    assert Calendar.from_ical(response["body"]).walk("VEVENT") == []
    assert repo.snapshot()["501"]["status"] == "cancelled"
    repo.revoke_subscription(owner["id"])
    assert serve(request, repo, client, later + timedelta(hours=1))["statusCode"] == 404
    assert requests == []
