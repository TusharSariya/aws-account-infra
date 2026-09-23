from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from booker.calendar_feed import serve
from booker.calendar_ics import render_calendar
from icalendar import Calendar


def reservation(**changes):
    return {
        "reservation_id": "reservation-1",
        "equipment_id": 1,
        "court": "Court 1",
        "location": "Ches Penney; YMCA, St. John's",
        "status": "confirmed",
        "start": "2026-03-08T03:30:00-02:30",
        "end": "2026-03-08T04:30:00-02:30",
        "updated_at": "2026-03-01T12:00:00Z",
        "sequence": 0,
        **changes,
    }


@pytest.fixture
def repository():
    repo = Mock()
    repo.validate_token.return_value = True
    repo.get_metadata.return_value = {"initialized": True}
    repo.list_events.return_value = [reservation()]
    repo.claim_refresh.return_value = None
    return repo


def request(**extra):
    return {"pathParameters": {"token": "secret-token"}, **extra}


def test_invalid_token_cannot_read_or_refresh(repository):
    repository.validate_token.return_value = False
    client = Mock()
    assert serve(request(), repository, client)["statusCode"] == 404
    repository.get_metadata.assert_not_called()
    repository.list_events.assert_not_called()
    repository.claim_refresh.assert_not_called()
    client.invoke.assert_not_called()


def test_uninitialized_vs_successfully_empty(repository, monkeypatch):
    monkeypatch.setenv("CALENDAR_RECONCILE_FUNCTION", "reconcile")
    repository.get_metadata.return_value = {}
    repository.claim_refresh.return_value = "lease"
    client = Mock()
    client.invoke.return_value = {"StatusCode": 202}
    response = serve(request(), repository, client)
    assert response["statusCode"] == 503
    assert response["headers"]["Retry-After"] == "60"
    client.invoke.assert_called_once()
    repository.get_metadata.return_value = {"initialized": True}
    repository.list_events.return_value = []
    response = serve(request(), repository, client)
    assert response["statusCode"] == 200
    assert not Calendar.from_ical(response["body"]).walk("VEVENT")


def test_conditional_response_still_evaluates_refresh(repository):
    first = serve(request(), repository, Mock())
    second = serve(
        request(headers={"If-None-Match": "W/" + first["headers"]["ETag"]}),
        repository,
        Mock(),
    )
    assert second["statusCode"] == 304
    assert second["body"] == ""
    assert repository.claim_refresh.call_count == 2


def test_background_refresh_only_affects_next_fetch(repository, monkeypatch):
    monkeypatch.setenv("CALENDAR_RECONCILE_FUNCTION", "reconcile")
    repository.claim_refresh.return_value = "lease"
    client = Mock()

    def refresh(**kwargs):
        repository.list_events.return_value = []
        return {"StatusCode": 202}

    client.invoke.side_effect = refresh
    first = serve(request(), repository, client)
    second = serve(request(), repository, client)
    assert len(Calendar.from_ical(first["body"]).walk("VEVENT")) == 1
    assert not Calendar.from_ical(second["body"]).walk("VEVENT")


def test_invocation_failure_releases_lease_without_exposing_token(
    repository, monkeypatch, caplog
):
    monkeypatch.setenv("CALENDAR_RECONCILE_FUNCTION", "reconcile")
    repository.claim_refresh.return_value = "lease"
    client = Mock()
    client.invoke.side_effect = RuntimeError("secret-token")
    assert serve(request(), repository, client)["statusCode"] == 200
    repository.release_refresh.assert_called_once_with("lease")
    assert "secret-token" not in caplog.text


def test_ics_stable_identity_and_newfoundland_dst():
    winter = reservation(
        start="2026-01-01T09:00:00-03:30", end="2026-01-01T10:00:00-03:30"
    )
    summer = reservation(
        start="2026-07-01T09:00:00-02:30", end="2026-07-01T10:00:00-02:30", sequence=1
    )
    first = Calendar.from_ical(render_calendar([winter])).walk("VEVENT")[0]
    second = Calendar.from_ical(render_calendar([summer])).walk("VEVENT")[0]
    assert first["UID"] == second["UID"]
    assert first.decoded("DTSTART") == datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
    assert second.decoded("DTSTART") == datetime(2026, 7, 1, 11, 30, tzinfo=UTC)
    assert second.decoded("SEQUENCE") == 1
    assert str(first["LOCATION"]) == winter["location"]
    assert render_calendar([winter]) == render_calendar([winter])
    assert not Calendar.from_ical(
        render_calendar([reservation(status="cancelled")])
    ).walk("VEVENT")
