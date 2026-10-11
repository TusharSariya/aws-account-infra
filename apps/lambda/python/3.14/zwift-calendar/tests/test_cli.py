import io
import json
from unittest.mock import Mock

from zwift_calendar import cli


def test_sync_waits_for_shared_lease_without_retrying_errors(monkeypatch):
    monkeypatch.setattr("sys.argv", ["zwift", "sync"])
    functions = Mock()
    functions.invoke.side_effect = [
        {"Payload": io.BytesIO(json.dumps({"status": status}).encode())}
        for status in ("busy", "busy", "ok")
    ]
    monkeypatch.setattr(cli, "client", lambda _: functions)
    sleep = Mock()
    monkeypatch.setattr(cli.time, "sleep", sleep)
    assert cli.main() == 0
    assert sleep.call_count == 2
    functions.invoke.side_effect = None
    functions.invoke.return_value = {
        "FunctionError": "Unhandled",
        "Payload": io.BytesIO(b"{}"),
    }
    functions.reset_mock()
    assert cli.main() == 1
    assert functions.invoke.call_count == 1
