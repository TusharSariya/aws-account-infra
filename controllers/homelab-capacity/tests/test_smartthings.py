"""HTTP contract tests; no cloud credentials or real devices are used."""

import json
from io import BytesIO
from urllib.error import HTTPError

import pytest
from homelab_capacity.smartthings import SmartThings


def adapter(tmp_path, replies, *, expires=10000):
    path = tmp_path / "credentials.json"
    path.write_text(
        json.dumps(
            {
                "access_token": "secret",
                "expires_at": expires,
                "client_id": "client",
                "client_secret": "client-secret",
                "refresh_token": "refresh",
            }
        )
    )
    path.chmod(0o600)
    requests = []

    def opener(request, timeout):
        assert timeout == 15
        requests.append(request)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return BytesIO(json.dumps(reply).encode())

    return SmartThings(path, opener=opener, clock=lambda: 1000), requests


def test_switch_uses_device_and_component_ids_and_does_not_assume_completion(tmp_path):
    api, requests = adapter(
        tmp_path, [{"results": [{"id": "command", "status": "ACCEPTED"}]}]
    )
    assert (
        api.switch({"device_id": "immutable-id", "component_id": "outlet2"}, "off")
        == "command"
    )
    request = requests[0]
    assert (
        request.full_url
        == "https://api.smartthings.com/v1/devices/immutable-id/commands"
    )
    assert json.loads(request.data) == {
        "commands": [
            {
                "component": "outlet2",
                "capability": "switch",
                "command": "off",
                "arguments": [],
            }
        ]
    }


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError(),
        HTTPError("https://api.smartthings.com", 401, "private-response", {}, None),
    ],
)
def test_failed_write_is_not_retried_and_does_not_expose_secret(tmp_path, error):
    api, requests = adapter(tmp_path, [error])
    with pytest.raises(RuntimeError) as caught:
        api.switch({"device_id": "id", "component_id": "main"}, "off")
    assert len(requests) == 1
    assert "private-response" not in str(caught.value)
    assert "secret" not in str(caught.value)


def test_refresh_rotates_and_persists_before_using_new_access_token(tmp_path):
    api, requests = adapter(
        tmp_path,
        [
            {"access_token": "new", "refresh_token": "new-refresh", "expires_in": 3600},
            {"items": []},
        ],
        expires=0,
    )
    assert api.discover() == []
    assert requests[0].full_url == "https://api.smartthings.com/v1/oauth/token"
    assert requests[1].get_header("Authorization") == "Bearer new"
    assert api.credentials()["refresh_token"] == "new-refresh"
    assert api.credentials()["expires_at"] == 4600
    assert api.path.stat().st_mode & 0o077 == 0


def test_offline_device_and_bad_state_are_never_off(tmp_path):
    api, _ = adapter(tmp_path, [{"state": "OFFLINE"}, {"switch": {"value": "off"}}])
    with pytest.raises(RuntimeError, match="offline or unknown"):
        api.status({"device_id": "id", "component_id": "main"})


def test_status_returns_device_event_time_separately_from_read_time(tmp_path):
    api, _ = adapter(
        tmp_path,
        [
            {"state": "ONLINE"},
            {"switch": {"value": "off", "timestamp": "1970-01-01T00:00:01Z"}},
        ],
    )
    sample = api.status({"device_id": "id", "component_id": "main"})
    assert sample == {"state": "off", "changed_at": 1, "observed_at": 1000}


def test_credentials_with_public_permissions_are_rejected(tmp_path):
    api, requests = adapter(tmp_path, [])
    api.path.chmod(0o644)
    with pytest.raises(PermissionError):
        api.discover()
    assert not requests


def test_refresh_timeout_persists_uncertainty_and_never_replays(tmp_path):
    api, requests = adapter(tmp_path, [TimeoutError()], expires=2000)
    with pytest.raises(RuntimeError):
        api.token()
    assert api.health()["refresh_uncertain"]
    with pytest.raises(RuntimeError, match="uncertain"):
        api.token(force_refresh=True)
    assert len(requests) == 1


def test_refresh_is_proactive_and_records_verification(tmp_path):
    api, requests = adapter(
        tmp_path,
        [{"access_token": "new", "refresh_token": "rotated", "expires_in": 86400}],
        expires=4000,
    )
    assert api.token() == "new"
    assert api.health()["refresh_verified"]
    assert not api.health()["refresh_uncertain"]
    assert len(requests) == 1


def test_server_expiry_pat_uses_api_without_inventing_deadline(tmp_path):
    api, requests = adapter(tmp_path, [{"items": []}])
    api.path.write_text(json.dumps({"access_token": "secret", "expiry_policy": "server"}))
    api.clock = lambda: 10**12
    assert api.health()["expires_at"] is None
    assert api.health()["remaining_seconds"] is None
    assert api.discover() == []
    assert len(requests) == 1


def test_server_expiry_pat_still_rejects_real_401_without_retry(tmp_path):
    api, requests = adapter(tmp_path, [HTTPError("https://api.smartthings.com", 401, "private", {}, None)])
    api.path.write_text(json.dumps({"access_token": "secret", "expiry_policy": "server"}))
    with pytest.raises(RuntimeError, match="requires observation"):
        api.discover()
    assert len(requests) == 1


def test_missing_pat_expiry_without_opt_in_remains_invalid(tmp_path):
    api, requests = adapter(tmp_path, [])
    api.path.write_text(json.dumps({"access_token": "secret"}))
    with pytest.raises(RuntimeError, match="expired"):
        api.discover()
    assert not requests


def test_server_policy_does_not_override_oauth_refresh(tmp_path):
    api, requests = adapter(tmp_path, [
        {"access_token": "new", "expires_in": 7200}, {"items": []}
    ], expires=0)
    api.path.write_text(json.dumps(api.credentials() | {"expiry_policy": "server"}))
    assert api.discover() == []
    assert len(requests) == 2
    assert api.health()["remaining_seconds"] == 7200
