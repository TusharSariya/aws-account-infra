from io import BytesIO
from unittest.mock import Mock

import pytest
from booker import calendar_cli, cli


@pytest.mark.parametrize(
    "argv",
    [
        ["subscription", "create", "friend"],
        ["subscription", "list"],
        ["subscription", "revoke", "id"],
        ["calendar", "subscription"],
    ],
)
def test_subscription_commands_are_gone(argv):
    with pytest.raises(SystemExit) as exc:
        calendar_cli.main(argv)
    assert exc.value.code == 2


def test_top_level_cli_rejects_subscription(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["subscription", "list"])
    assert exc.value.code == 2


def test_calendar_sync_command_prints_result(monkeypatch, capsys):
    monkeypatch.setenv("CALENDAR_RECONCILE_FUNCTION", "reconcile")
    client = Mock()
    client.invoke.return_value = {"Payload": BytesIO(b'{"status":"synced","count":3}')}
    monkeypatch.setattr(calendar_cli, "_lambda_client", lambda: client)
    assert cli.main(["calendar", "sync"]) == 0
    assert '"count": 3' in capsys.readouterr().out
    assert client.invoke.call_args.kwargs["FunctionName"] == "reconcile"


def test_calendar_sync_failure_is_sanitized(monkeypatch, capsys):
    monkeypatch.setenv("CALENDAR_RECONCILE_FUNCTION", "reconcile")
    client = Mock()
    client.invoke.side_effect = RuntimeError("secret-detail")
    monkeypatch.setattr(calendar_cli, "_lambda_client", lambda: client)
    assert calendar_cli.main(["calendar", "sync"]) == 1
    captured = capsys.readouterr()
    assert "secret-detail" not in captured.out + captured.err


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
