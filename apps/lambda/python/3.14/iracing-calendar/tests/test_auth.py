import copy
import json
import time
from urllib.error import HTTPError

import boto3
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from moto import mock_aws

from iracing_calendar import auth, sync
from iracing_calendar.store import Conflict, Store

CONFIG = {
    "client_id": "test-client",
    "client_secret": "client-secret",
    "allowed_username": "test@example.invalid",
    "allowed_cust_id": 42,
}
PAIR = {
    "access_token": "access",
    "refresh_token": "refresh",
    "token_type": "Bearer",
    "scope": "iracing.auth",
    "expires_in": 600,
    "refresh_token_expires_in": 604800,
}


@pytest.fixture
def leased(monkeypatch):
    with mock_aws():
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket="auth-test")
        store = Store(s3, "auth-test")
        store.write({"ics": "last-good", "last_success": 1})
        _, etag, owner = store.claim()
        api = boto3.client("ssm")
        secrets = auth.Parameters("client", "tokens", api)
        exchanges = []

        def exchange(url, form):
            exchanges.append(copy.deepcopy(form))
            assert secrets.read("tokens") == {"state": "exchange_pending"}
            return PAIR

        service = auth.Auth(
            secrets, store, etag, owner, exchange=exchange, verify=lambda *_: None
        )
        yield service, exchanges


def test_official_masking_vector():
    assert (
        auth.mask(
            "Anagram-tactics-FOOTING-OPACITY-SHONE-keenly", " John.West@iracing.com "
        )
        == "KIhAi2ynNPWvJsebdluGaBaPTRaUACqTPDCfyUuv46Y="
    )


def test_bootstrap_rotation_and_read_only_status(leased):
    service, exchanges = leased
    assert service.bootstrap(CONFIG, CONFIG["allowed_username"], "password") == "access"
    assert exchanges[0]["password"] == auth.mask("password", CONFIG["allowed_username"])
    assert exchanges[0]["client_secret"] == auth.mask("client-secret", "test-client")
    assert "password" not in json.dumps(service.secrets.read("client"))
    assert "password" not in json.dumps(service.secrets.read("tokens"))
    before = service.secrets.read("tokens")
    assert service.secrets.status()["reauthentication_required"] is False
    assert service.secrets.read("tokens") == before
    assert service.access() == "access"
    assert len(exchanges) == 1
    service.clock = lambda: time.time() + 500
    # Extend the test lease to cover simulated passage of time.
    state, _ = service.store.read()
    state["lease_until"] += 500
    service.etag = service.store.write(state, service.etag)
    assert service.access() == "access"
    assert exchanges[-1]["grant_type"] == "refresh_token"
    assert exchanges[-1]["refresh_token"] == "refresh"
    assert "password" not in exchanges[-1]
    assert service.store.read()[0]["ics"] == "last-good"


def test_exchange_timeout_never_replays_refresh(leased):
    service, exchanges = leased
    service.bootstrap(CONFIG, CONFIG["allowed_username"], "password")
    tokens = service.secrets.read("tokens")
    tokens["access_expires_at"] = 0
    service.secrets.write("tokens", tokens)

    def fail(*args):
        exchanges.append("attempt")
        raise auth.AuthError("Exchange outcome unknown")

    service.exchange = fail
    with pytest.raises(auth.AuthError):
        service.access()
    with pytest.raises(auth.AuthError, match="bootstrap required"):
        service.access()
    assert exchanges.count("attempt") == 1
    assert service.secrets.status()["reauthentication_required"]


def test_persist_tokens_before_verification_and_fail_closed(leased):
    service, _ = leased

    def verify(*args):
        assert service.secrets.read("tokens")["refresh_token"] == "refresh"
        raise auth.AuthError("invalid account")

    service.verify = verify
    with pytest.raises(auth.AuthError, match="invalid account"):
        service.bootstrap(CONFIG, CONFIG["allowed_username"], "password")
    assert service.secrets.read("tokens")["state"] == "unverified"
    with pytest.raises(auth.AuthError, match="bootstrap required"):
        service.access()


def test_marker_write_failure_prevents_exchange(leased, monkeypatch):
    service, exchanges = leased
    service.secrets.write("client", CONFIG)
    service.secrets.write(
        "tokens",
        {
            "state": "ready",
            "refresh_token": "old",
            "refresh_expires_at": time.time() + 1000,
        },
    )

    def fail(*args):
        raise auth.AuthError("Persistence failed")

    monkeypatch.setattr(service.secrets, "write", fail)
    with pytest.raises(auth.AuthError):
        service.access()
    assert exchanges == []


def test_issued_pair_persistence_failure_cannot_replay(leased, monkeypatch):
    service, exchanges = leased
    write = service.secrets.write

    def fail_pair(secret, value):
        if value.get("state") == "unverified":
            raise auth.AuthError("Persistence failed")
        return write(secret, value)

    monkeypatch.setattr(service.secrets, "write", fail_pair)
    with pytest.raises(auth.AuthError):
        service.bootstrap(CONFIG, CONFIG["allowed_username"], "password")
    assert service.secrets.read("tokens") == {"state": "exchange_pending"}
    with pytest.raises(auth.AuthError):
        service.access()
    assert len(exchanges) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"refresh_token": ""},
        {"expires_in": -1},
        {"scope": "other"},
        {"refresh_token_expires_in": "604800"},
    ],
)
def test_malformed_response_requires_reauthentication(leased, change):
    service, _ = leased
    service.exchange = lambda *_: PAIR | change
    with pytest.raises(auth.AuthError, match="Invalid token response"):
        service.bootstrap(CONFIG, CONFIG["allowed_username"], "password")
    assert service.secrets.read("tokens")["state"] == "exchange_pending"


def test_cli_status_never_prints_credentials(leased, monkeypatch, capsys):
    from iracing_calendar import cli

    service, _ = leased
    service.bootstrap(CONFIG, CONFIG["allowed_username"], "password")
    monkeypatch.setattr(auth, "Parameters", lambda *_: service.secrets)
    monkeypatch.setattr(
        "sys.argv",
        [
            "cli",
            "auth",
            "status",
            "--client-parameter",
            "client",
            "--token-parameter",
            "tokens",
        ],
    )
    assert cli.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert set(result) == {
        "configured",
        "reauthentication_required",
        "access_expires_at",
        "refresh_expires_at",
    }


def test_bootstrap_reuses_saved_client_and_prompts_only_for_account(
    leased, monkeypatch, capsys
):
    from iracing_calendar import cli, store

    service, _ = leased
    service.store.release(service.etag, service.owner)
    service.secrets.write(
        "client", {k: v for k, v in CONFIG.items() if k != "allowed_username"}
    )
    monkeypatch.setattr(auth, "Parameters", lambda *_: service.secrets)
    monkeypatch.setattr(store, "Store", lambda **_: service.store)
    prompts = []

    def prompt(label):
        prompts.append(label)
        return CONFIG["allowed_username"] if "username" in label else "private-password"

    def bootstrap(self, config, username, password):
        assert config == CONFIG
        assert username == CONFIG["allowed_username"]
        assert password == "private-password"

    monkeypatch.setattr(cli.getpass, "getpass", prompt)
    monkeypatch.setattr(auth.Auth, "bootstrap", bootstrap)
    monkeypatch.setattr(
        "sys.argv",
        [
            "cli",
            "auth",
            "bootstrap",
            "--client-parameter",
            "client",
            "--token-parameter",
            "tokens",
            "--bucket",
            "auth-test",
        ],
    )
    assert cli.main() == 0
    assert prompts == [
        "Registered allowed username: ",
        "iRacing account password (never stored): ",
    ]
    output = capsys.readouterr().out
    assert "private-password" not in output and "client-secret" not in output
    assert "lease" not in service.store.read()[0]


def test_concurrent_or_expired_lease_cannot_exchange(leased):
    service, exchanges = leased
    with pytest.raises(Conflict):
        service.store.claim()
    service.clock = lambda: time.time() + 601
    with pytest.raises(Conflict):
        service.bootstrap(CONFIG, CONFIG["allowed_username"], "password")
    assert exchanges == []


def test_wrong_username_and_expired_refresh(leased):
    service, exchanges = leased
    with pytest.raises(auth.AuthError, match="allowed user"):
        service.bootstrap(CONFIG, "wrong", "password")
    service.secrets.write("tokens", {"state": "ready", "refresh_expires_at": 1})
    with pytest.raises(auth.AuthError, match="bootstrap required"):
        service.access()
    assert exchanges == []


@pytest.mark.parametrize("status", [302, 400, 429, 500])
def test_transport_redacts_errors_and_never_retries(monkeypatch, status):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            raise HTTPError(request.full_url, status, "secret response", {}, None)

    monkeypatch.setattr(auth, "build_opener", lambda *args: Opener())
    with pytest.raises(auth.AuthError) as error:
        auth.request_json(auth.TOKEN, {"password": "secret-password"})
    assert len(calls) == 1
    assert "secret" not in str(error.value)
    assert error.value.__suppress_context__
    assert (
        auth.NoRedirect().redirect_request(
            None, None, 302, None, {}, "https://evil.invalid"
        )
        is None
    )


def signed_token(changes=None):
    private = Ed25519PrivateKey.generate()
    key = json.loads(jwt.algorithms.OKPAlgorithm.to_jwk(private.public_key())) | {
        "kid": "test"
    }
    now = int(time.time())
    claims = {
        "iss": auth.ISSUER,
        "exp": now + 600,
        "iat": now - 1,
        "auth_time": now - 2,
        "aud": ["data-server", "oauth-api", "test-client"],
        "scope": "iracing.auth",
        "client_id": "test-client",
        "iracing_cust_id": 42,
        "sub": None,
    }
    claims.update(changes or {})
    token = jwt.encode(
        claims, private, algorithm="EdDSA", headers={"kid": "test", "jku": auth.JWKS}
    )
    return token, key


def test_signature_and_operational_claims():
    token, key = signed_token()
    auth.verify_access(token, CONFIG, fetch=lambda _: {"keys": [key]})
    _, other = signed_token()
    with pytest.raises(auth.AuthError):
        auth.verify_access(token, CONFIG, fetch=lambda _: {"keys": [other]})
    with pytest.raises(auth.AuthError):
        auth.verify_access(token, CONFIG, fetch=lambda _: {"keys": [key, key]})


@pytest.mark.parametrize(
    "changes",
    [
        {"aud": ["oauth-api", "test-client"]},
        {"iracing_cust_id": 99},
        {"scope": "iracing.profile"},
        {"client_id": "other"},
        {"exp": 1},
        {"auth_time": time.time() + 100},
        {"iracing_env": "other"},
    ],
)
def test_reject_invalid_claims(changes):
    token, key = signed_token(changes)
    with pytest.raises(auth.AuthError):
        auth.verify_access(token, CONFIG, fetch=lambda _: {"keys": [key]})


def test_hourly_action_preserves_snapshot_and_releases_lease(leased, monkeypatch):
    service, _ = leased
    service.store.release(service.etag, service.owner)
    monkeypatch.setattr(sync, "Store", lambda: service.store)
    monkeypatch.setattr(auth.Auth, "access", lambda self: "access")
    monkeypatch.setattr(sync, "authentication", lambda *_: service)
    monkeypatch.setenv("IRACING_CLIENT_PARAMETER", "client")
    monkeypatch.setenv("IRACING_TOKEN_PARAMETER", "tokens")
    assert sync.lambda_handler({"action": "auth"}, None)["status"] == "ok"
    assert service.store.read()[0] == {"ics": "last-good", "last_success": 1}
