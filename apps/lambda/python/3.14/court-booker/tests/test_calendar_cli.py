from io import BytesIO
from unittest.mock import Mock

import pytest
from booker import calendar_cli


def test_create_prints_url_once_and_list_never_exposes_tokens(monkeypatch, capsys):
    repository = Mock()
    repository.create_subscription.return_value = {
        "id": "id",
        "label": "Friend",
        "token": "secret-token",
    }
    repository.list_subscriptions.return_value = [
        {
            "id": "id",
            "label": "Friend",
            "token": "secret-token",
            "token_hash": "secret-hash",
        }
    ]
    monkeypatch.setattr(calendar_cli, "CalendarRepository", lambda: repository)
    assert (
        calendar_cli.main(
            ["subscription", "create", "Friend", "--base-url", "https://example.com"]
        )
        == 0
    )
    assert capsys.readouterr().out.count("secret-token") == 1
    assert calendar_cli.main(["subscription", "list"]) == 0
    assert "secret" not in capsys.readouterr().out
    repository.revoke_subscription.return_value = True
    assert calendar_cli.main(["subscription", "revoke", "id"]) == 0
    repository.revoke_subscription.assert_called_once_with("id")


def test_sync_waits_for_busy_then_reports_completion(monkeypatch):
    monkeypatch.setenv("CALENDAR_RECONCILE_FUNCTION", "reconcile")
    client = Mock()
    client.invoke.side_effect = [
        {"Payload": BytesIO(b'{"status":"busy"}')},
        {"Payload": BytesIO(b'{"status":"synced","count":2}')},
    ]
    sleep = Mock()
    assert calendar_cli.sync(client, sleep=sleep)["count"] == 2
    sleep.assert_called_once()
    assert client.invoke.call_count == 2


def test_sync_error_does_not_return_upstream_payload(monkeypatch):
    monkeypatch.setenv("CALENDAR_RECONCILE_FUNCTION", "reconcile")
    client = Mock()
    client.invoke.return_value = {
        "FunctionError": "Unhandled",
        "Payload": BytesIO(b"secret"),
    }
    with pytest.raises(RuntimeError, match="Calendar sync failed"):
        calendar_cli.sync(client)
