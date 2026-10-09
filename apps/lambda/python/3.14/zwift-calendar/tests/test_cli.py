"""Synchronous rollout checks must await a completed refresh without replay."""

import io
import json
from unittest.mock import Mock

import pytest

from zwift_calendar import cli
from zwift_calendar.storage import client


def test_lambda_invocation_can_wait_for_the_sync_deadline_without_retries(monkeypatch):
    from zwift_calendar import storage

    factory = Mock()
    monkeypatch.setattr(storage.boto3, "client", factory)
    client("lambda")
    config = factory.call_args.kwargs["config"]
    assert config.read_timeout > 540
    assert config.retries["total_max_attempts"] == 1
    client("s3")
    assert factory.call_args.kwargs["config"].read_timeout == 10


@pytest.mark.parametrize("status,exit_code", [("ok", 0), ("busy", 1), (None, 1)])
def test_sync_requires_confirmed_completion(monkeypatch, status, exit_code):
    monkeypatch.setattr("sys.argv", ["zwift-calendar", "sync"])
    invoke = Mock(
        return_value={"Payload": io.BytesIO(json.dumps({"status": status}).encode())}
    )
    monkeypatch.setattr(cli, "client", Mock(return_value=Mock(invoke=invoke)))
    assert cli.main() == exit_code
    invoke.assert_called_once()
