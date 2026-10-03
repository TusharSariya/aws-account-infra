import json
import time

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError
from moto import mock_aws
from test_auth import CONFIG

from iracing_calendar.auth import Auth, AuthError, Parameters
from iracing_calendar.auth_migration import migrate_auth
from iracing_calendar.store import Conflict, Store


@pytest.fixture
def migration(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket="migration-test")
        store = Store(s3, "migration-test")
        store.write({"ics": "last-good", "last_success": 1})
        legacy = boto3.client("secretsmanager")
        tokens = {
            "state": "ready",
            "access_token": "access",
            "refresh_token": "single-use",
            "access_expires_at": time.time() + 600,
            "refresh_expires_at": time.time() + 86400,
        }
        legacy.create_secret(Name="client", SecretString=json.dumps(CONFIG))
        legacy.create_secret(Name="tokens", SecretString=json.dumps(tokens))
        parameters = Parameters("/test/client", "/test/tokens")
        yield parameters, store, legacy


def migrate(migration):
    parameters, store, legacy = migration
    return migrate_auth(parameters, store, "client", "tokens", legacy)


def test_migration_keeps_tokens_and_feed_and_retries_after_legacy_retirement(migration):
    parameters, store, legacy = migration
    assert migrate(migration) == {"status": "migrated"}
    assert parameters.read("/test/client") == CONFIG
    assert parameters.read("/test/tokens")["refresh_token"] == "single-use"
    tombstone = json.loads(legacy.get_secret_value(SecretId="tokens")["SecretString"])
    assert tombstone["state"] == "migrated_to_ssm" and "refresh_token" not in tombstone
    state, _ = store.read()
    assert state == {
        "ics": "last-good",
        "last_success": 1,
        "auth_storage": {"client": "/test/client", "tokens": "/test/tokens"},
    }
    legacy.delete_secret(SecretId="client", ForceDeleteWithoutRecovery=True)
    legacy.delete_secret(SecretId="tokens", ForceDeleteWithoutRecovery=True)
    assert migrate(migration) == {"status": "already_migrated"}


def test_oversized_token_rejects_before_changing_either_store(migration):
    parameters, _, legacy = migration
    source = json.loads(legacy.get_secret_value(SecretId="tokens")["SecretString"])
    source["refresh_token"] = "large" * 1000
    legacy.put_secret_value(SecretId="tokens", SecretString=json.dumps(source))
    with pytest.raises(AuthError, match="4 KB"):
        migrate(migration)
    assert parameters.read("/test/client") == parameters.read("/test/tokens") == {}
    assert (
        json.loads(legacy.get_secret_value(SecretId="tokens")["SecretString"]) == source
    )


def test_uncertain_legacy_write_resumes_staged_transfer(migration, monkeypatch):
    parameters, store, legacy = migration
    write = legacy.put_secret_value

    def uncertain(**kwargs):
        write(**kwargs)
        raise EndpointConnectionError(endpoint_url="private-response")

    monkeypatch.setattr(legacy, "put_secret_value", uncertain)
    with pytest.raises(AuthError, match="retry migration") as error:
        migrate(migration)
    assert "private-response" not in str(error.value)
    assert parameters.read("/test/tokens")["state"] == "migration_pending"
    # Staged data cannot authenticate, even though it contains a refresh token.
    _, etag, owner = store.claim()
    try:
        with pytest.raises(AuthError, match="bootstrap required"):
            Auth(parameters, store, etag, owner).access()
    finally:
        store.release(etag, owner)
    monkeypatch.setattr(legacy, "put_secret_value", write)
    assert migrate(migration) == {"status": "migrated"}


def test_retry_before_legacy_disable_uses_latest_token_not_staged_copy(
    migration, monkeypatch
):
    parameters, _, legacy = migration
    write = legacy.put_secret_value

    def fail(**kwargs):
        raise EndpointConnectionError(endpoint_url="private-response")

    monkeypatch.setattr(legacy, "put_secret_value", fail)
    with pytest.raises(AuthError):
        migrate(migration)
    source = json.loads(legacy.get_secret_value(SecretId="tokens")["SecretString"])
    write(
        SecretId="tokens",
        SecretString=json.dumps(source | {"refresh_token": "newer-token"}),
    )
    monkeypatch.setattr(legacy, "put_secret_value", write)
    migrate(migration)
    assert parameters.read("/test/tokens")["refresh_token"] == "newer-token"


def test_activation_failure_can_resume_without_replaying_oauth(migration, monkeypatch):
    parameters, _, _ = migration
    write = parameters.write

    def fail(name, value):
        if value.get("state") == "ready":
            raise AuthError("Persistence failed")
        write(name, value)

    monkeypatch.setattr(parameters, "write", fail)
    with pytest.raises(AuthError, match="Persistence"):
        migrate(migration)
    monkeypatch.setattr(parameters, "write", write)
    assert migrate(migration) == {"status": "migrated"}


def test_snapshot_publish_failure_can_resume(migration, monkeypatch):
    _, store, _ = migration
    publish = store.publish

    def fail(data, etag, owner):
        if "auth_storage" in data:
            raise Conflict("Publish interrupted")
        publish(data, etag, owner)

    monkeypatch.setattr(store, "publish", fail)
    with pytest.raises(Conflict):
        migrate(migration)
    monkeypatch.setattr(store, "publish", publish)
    assert migrate(migration) == {"status": "migrated"}


def test_concurrent_migration_is_rejected(migration):
    parameters, store, _ = migration
    _, etag, owner = store.claim()
    try:
        with pytest.raises(Conflict):
            migrate(migration)
        assert parameters.read("/test/tokens") == {}
    finally:
        store.release(etag, owner)


@pytest.mark.parametrize("state", ["exchange_pending", "unverified"])
def test_unknown_exchange_outcome_is_never_migrated(migration, state):
    parameters, _, legacy = migration
    legacy.put_secret_value(
        SecretId="tokens", SecretString=json.dumps({"state": state})
    )
    with pytest.raises(AuthError, match="not safely transferable"):
        migrate(migration)
    assert parameters.read("/test/tokens") == {}


def test_existing_active_destination_is_not_overwritten(migration):
    parameters, _, _ = migration
    parameters.write("/test/tokens", {"state": "ready", "refresh_token": "different"})
    with pytest.raises(AuthError, match="already in use"):
        migrate(migration)
    assert parameters.read("/test/tokens")["refresh_token"] == "different"
