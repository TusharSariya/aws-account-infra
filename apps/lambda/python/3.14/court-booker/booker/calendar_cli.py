"""IAM-authenticated explicit read-only calendar sync."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from booker.secrets import _client_kwargs


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m booker")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("calendar").add_subparsers(
        dest="action", required=True
    ).add_parser("sync")
    return parser


def sync(client, *, timeout=300, sleep=time.sleep, clock=time.monotonic):
    deadline = clock() + timeout
    while True:
        response = client.invoke(
            FunctionName=os.environ["CALENDAR_RECONCILE_FUNCTION"],
            InvocationType="RequestResponse",
            Payload=b"{}",
        )
        if response.get("FunctionError"):
            raise RuntimeError("Calendar sync failed; check reconciliation alerts")
        result = json.loads(response["Payload"].read())
        if result.get("status") != "busy":
            if result.get("status") != "synced":
                raise RuntimeError("Calendar sync did not complete successfully")
            return result
        if clock() >= deadline:
            raise RuntimeError(
                "Calendar sync timed out waiting for the current refresh"
            )
        sleep(min(5, max(0, deadline - clock())))


def _lambda_client():
    return boto3.client(
        "lambda",
        **_client_kwargs(),
        config=Config(
            connect_timeout=5,
            read_timeout=290,
            retries={"total_max_attempts": 1, "mode": "standard"},
        ),
    )


def main(argv=None):
    build_parser().parse_args(argv)
    try:
        print(json.dumps(sync(_lambda_client()), sort_keys=True))
    except (BotoCoreError, ClientError, RuntimeError, KeyError, ValueError):
        # Never echo payloads, request URLs or secret-bearing exception strings.
        print(
            "Calendar operation failed; check AWS configuration and reconciliation alerts",
            file=sys.stderr,
        )
        return 1
    return 0
