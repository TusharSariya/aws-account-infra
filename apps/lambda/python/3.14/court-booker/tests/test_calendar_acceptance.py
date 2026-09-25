"""Exercise public and private feed polls through real repository/reconciliation boundaries."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from booker import calendar_feed
from booker.calendar_feed import PRIVATE_ROUTE, PUBLIC_ROUTE, serve
from booker.calendar_reconcile import reconcile
from booker.http import HeldReservation
from icalendar import Calendar
from moto import mock_aws
from test_calendar_storage import make_repo


@mock_aws
def test_manual_reservations_background_polls_and_key_rotation(monkeypatch):
    now = datetime(2026, 9, 23, 12, tzinfo=UTC)
    repo = make_repo()
    key = "k" * 43
    ssm = Mock()
    ssm.get_parameter.return_value = {"Parameter": {"Value": key}}
    calendar_feed._key_cache.clear()
    requests = []
    monkeypatch.setenv("CALENDAR_RECONCILE_FUNCTION", "synthetic-reconciler")
    monkeypatch.setenv("CALENDAR_PRIVATE_KEY_PARAMETER", "/test/calendar-private-key")

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
    request = {"routeKey": PRIVATE_ROUTE, "pathParameters": {"key": key}}
    public = {"routeKey": PUBLIC_ROUTE}
    assert serve(request, repo, client, now, ssm=ssm)["statusCode"] == 503
    # Both endpoints share a single refresh lease.
    assert serve(public, repo, client, now, ssm=ssm)["statusCode"] == 503
    assert len(requests) == 1
    reconcile(repo, upstream, config, credentials, requests.pop()["lease_id"], now=now)
    response = serve(request, repo, client, now, ssm=ssm)
    assert response["statusCode"] == 200
    event = Calendar.from_ical(response["body"]).walk("VEVENT")[0]
    assert event.decoded("dtstart") == datetime(2026, 9, 24, 19, 30, tzinfo=UTC)
    assert event.decoded("dtend") == datetime(2026, 9, 24, 21, tzinfo=UTC)
    request["headers"] = {"If-None-Match": response["headers"]["ETag"]}
    later = now + timedelta(minutes=15)
    assert serve(request, repo, client, later, ssm=ssm)["statusCode"] == 304
    assert len(requests) == 1
    rows.clear()  # Synthetic external cancellation: never call reserve/cancel APIs.
    reconcile(
        repo, upstream, config, credentials, requests.pop()["lease_id"], now=later
    )
    response = serve(request, repo, client, later, ssm=ssm)
    assert response["statusCode"] == 200
    assert Calendar.from_ical(response["body"]).walk("VEVENT") == []
    assert repo.snapshot()["501"]["status"] == "cancelled"
    # Rotation: once the cached key expires, the old key stops working.
    ssm.get_parameter.return_value = {"Parameter": {"Value": "n" * 43}}
    calendar_feed._key_cache.clear()
    assert (
        serve(request, repo, client, later + timedelta(hours=1), ssm=ssm)["statusCode"]
        == 404
    )
    assert requests == []
    calendar_feed._key_cache.clear()
