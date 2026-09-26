import hashlib
import logging
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from booker import calendar_feed
from booker.calendar_feed import PRIVATE_ROUTE, PUBLIC_ROUTE, serve
from botocore.exceptions import ClientError
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


KEY = "k" * 43
PARAMETER = "/staging/court-booker-api/calendar-private-key"


@pytest.fixture(autouse=True)
def private_key(monkeypatch):
    monkeypatch.setenv("CALENDAR_PRIVATE_KEY_PARAMETER", PARAMETER)
    calendar_feed._key_cache.clear()
    yield
    calendar_feed._key_cache.clear()


def ssm_with(value=KEY, error=None):
    ssm = Mock()
    if error is not None:
        ssm.get_parameter.side_effect = error
    else:
        ssm.get_parameter.return_value = {"Parameter": {"Value": value}}
    return ssm


@pytest.fixture
def repository():
    repo = Mock()
    repo.get_metadata.return_value = {"initialized": True}
    repo.list_events.return_value = [
        reservation(),
        reservation(
            reservation_id="reservation-2", visibility="private", title="Coaching"
        ),
    ]
    repo.claim_refresh.return_value = None
    return repo


def public_request(**extra):
    return {
        "routeKey": PUBLIC_ROUTE,
        "rawPath": "/calendars/public/bookings.ics",
        **extra,
    }


def private_request(key=KEY, **extra):
    return {
        "routeKey": PRIVATE_ROUTE,
        "pathParameters": {"key": key},
        **extra,
    }


def request(**extra):
    return public_request(**extra)


def summaries(response):
    calendar = Calendar.from_ical(response["body"])
    return str(calendar["X-WR-CALNAME"]), sorted(
        str(event["SUMMARY"]) for event in calendar.walk("VEVENT")
    )


def assert_rejected(response, repository, client):
    assert response["statusCode"] == 404
    assert response["body"] == "Not found"
    repository.get_metadata.assert_not_called()
    repository.list_events.assert_not_called()
    repository.claim_refresh.assert_not_called()
    client.invoke.assert_not_called()


def test_public_route_omits_private_events_and_needs_no_key(repository, monkeypatch):
    monkeypatch.delenv("CALENDAR_PRIVATE_KEY_PARAMETER")
    ssm = ssm_with()
    response = serve(public_request(), repository, Mock(), ssm=ssm)
    assert response["statusCode"] == 200
    assert summaries(response) == ("Court bookings", ["Court 1"])
    assert "Coaching" not in response["body"]
    assert response["headers"]["Cache-Control"] == "private, no-cache"
    assert response["headers"]["Referrer-Policy"] == "no-referrer"
    ssm.get_parameter.assert_not_called()


def test_private_route_with_correct_key_includes_private_events(repository):
    ssm = ssm_with()
    response = serve(private_request(), repository, Mock(), ssm=ssm)
    assert response["statusCode"] == 200
    assert summaries(response) == (
        "Coaching (private)",
        ["Coaching - Court 1"],
    )
    ssm.get_parameter.assert_called_once_with(Name=PARAMETER, WithDecryption=True)
    public = serve(public_request(), repository, Mock(), ssm=ssm)
    assert public["headers"]["ETag"] != response["headers"]["ETag"]


def test_private_key_is_cached_per_container(repository):
    ssm = ssm_with()
    for _ in range(3):
        assert (
            serve(private_request(), repository, Mock(), ssm=ssm)["statusCode"] == 200
        )
    assert (
        serve(private_request("x" * 43), Mock(), Mock(), ssm=ssm)["statusCode"] == 404
    )
    ssm.get_parameter.assert_called_once()


def test_cached_key_expires_so_rotation_takes_effect():
    ssm = ssm_with()
    clock = Mock(return_value=0)
    assert calendar_feed._load_private_key_digest(ssm, clock=clock)
    ssm.get_parameter.return_value = {"Parameter": {"Value": "n" * 43}}
    clock.return_value = calendar_feed.KEY_CACHE_SECONDS - 1
    assert (
        calendar_feed._load_private_key_digest(ssm, clock=clock)
        == hashlib.sha256(KEY.encode()).digest()
    )
    clock.return_value = calendar_feed.KEY_CACHE_SECONDS
    assert (
        calendar_feed._load_private_key_digest(ssm, clock=clock)
        == hashlib.sha256(b"n" * 43).digest()
    )


@pytest.mark.parametrize(
    "event",
    [
        private_request("wrong" + KEY[5:]),
        private_request(KEY + "x"),
        private_request(KEY[:-1]),
        private_request(""),
        private_request(None),
        private_request("k" * 300),
        {"routeKey": PRIVATE_ROUTE},
        {"routeKey": PRIVATE_ROUTE, "pathParameters": None},
    ],
    ids=["wrong", "longer", "prefix", "empty", "none", "oversized", "missing", "null"],
)
def test_wrong_or_missing_key_is_not_found(repository, event):
    client = Mock()
    assert_rejected(
        serve(event, repository, client, ssm=ssm_with()), repository, client
    )


@pytest.mark.parametrize(
    "value", ["UNSET", "s" * 31, "", None], ids=["unset", "short", "empty", "none"]
)
def test_unusable_configured_key_fails_closed(repository, value, caplog):
    client = Mock()
    ssm = ssm_with(value)
    # Presenting the configured value itself must still be rejected.
    event = private_request(value or KEY)
    assert_rejected(serve(event, repository, client, ssm=ssm), repository, client)
    assert "Calendar private key is not configured" in caplog.text


def test_missing_parameter_env_fails_closed(repository, monkeypatch, caplog):
    monkeypatch.delenv("CALENDAR_PRIVATE_KEY_PARAMETER")
    client = Mock()
    ssm = ssm_with()
    assert_rejected(
        serve(private_request(), repository, client, ssm=ssm), repository, client
    )
    ssm.get_parameter.assert_not_called()
    assert KEY not in caplog.text


@pytest.mark.parametrize(
    "error",
    [
        ClientError(
            {"Error": {"Code": "ParameterNotFound", "Message": PARAMETER}},
            "GetParameter",
        ),
        ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": KEY}},
            "GetParameter",
        ),
        RuntimeError(KEY),
    ],
    ids=["not-found", "denied", "other"],
)
def test_ssm_errors_fail_closed_without_logging_key(repository, error, caplog):
    client = Mock()
    ssm = ssm_with(error=error)
    with caplog.at_level(logging.DEBUG):
        response = serve(private_request(), repository, client, ssm=ssm)
    assert_rejected(response, repository, client)
    assert "Calendar private key could not be loaded" in caplog.text
    assert KEY not in caplog.text
    assert PARAMETER not in caplog.text
    # Failures are not cached; a later request retries SSM.
    ssm.get_parameter.side_effect = None
    ssm.get_parameter.return_value = {"Parameter": {"Value": KEY}}
    assert serve(private_request(), repository, client, ssm=ssm)["statusCode"] == 200


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"routeKey": "$default"},
        {
            "routeKey": "GET /calendars/{token}/bookings.ics",
            "pathParameters": {"token": KEY},
        },
        {"routeKey": "POST /calendars/public/bookings.ics"},
        {"routeKey": "GET /calendars/private/bookings.ics"},
        {"rawPath": "/calendars/public/bookings.ics"},
    ],
    ids=["empty", "default", "legacy-token", "post", "private-no-key", "path-only"],
)
def test_unknown_route_is_not_found(repository, event):
    client = Mock()
    ssm = ssm_with()
    assert_rejected(serve(event, repository, client, ssm=ssm), repository, client)
    ssm.get_parameter.assert_not_called()


@pytest.mark.parametrize(
    "make", [public_request, private_request], ids=["public", "private"]
)
def test_both_routes_return_503_before_initialization(repository, monkeypatch, make):
    monkeypatch.setenv("CALENDAR_RECONCILE_FUNCTION", "reconcile")
    repository.get_metadata.return_value = {}
    repository.claim_refresh.return_value = "lease"
    client = Mock()
    client.invoke.return_value = {"StatusCode": 202}
    response = serve(make(), repository, client, ssm=ssm_with())
    assert response["statusCode"] == 503
    assert response["headers"]["Retry-After"] == "60"
    client.invoke.assert_called_once()


@pytest.mark.parametrize(
    "make", [public_request, private_request], ids=["public", "private"]
)
def test_both_routes_request_background_refresh(repository, monkeypatch, make):
    monkeypatch.setenv("CALENDAR_RECONCILE_FUNCTION", "reconcile")
    repository.claim_refresh.return_value = "lease"
    client = Mock()
    client.invoke.return_value = {"StatusCode": 202}
    assert serve(make(), repository, client, ssm=ssm_with())["statusCode"] == 200
    repository.claim_refresh.assert_called_once()
    assert client.invoke.call_args.kwargs["Payload"] == b'{"lease_id": "lease"}'


@pytest.mark.parametrize(
    "make", [public_request, private_request], ids=["public", "private"]
)
def test_etag_conditional_request_on_both_routes(repository, make):
    ssm = ssm_with()
    first = serve(make(), repository, Mock(), ssm=ssm)
    second = serve(
        make(headers={"If-None-Match": "W/" + first["headers"]["ETag"]}),
        repository,
        Mock(),
        ssm=ssm,
    )
    assert second["statusCode"] == 304
    assert second["body"] == ""
    assert repository.claim_refresh.call_count == 2


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


def test_invocation_failure_releases_lease_without_exposing_details(
    repository, monkeypatch, caplog
):
    monkeypatch.setenv("CALENDAR_RECONCILE_FUNCTION", "reconcile")
    repository.claim_refresh.return_value = "lease"
    client = Mock()
    client.invoke.side_effect = RuntimeError("secret-detail " + KEY)
    assert (
        serve(private_request(), repository, client, ssm=ssm_with())["statusCode"]
        == 200
    )
    repository.release_refresh.assert_called_once_with("lease")
    assert "secret-detail" not in caplog.text
    assert KEY not in caplog.text


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
