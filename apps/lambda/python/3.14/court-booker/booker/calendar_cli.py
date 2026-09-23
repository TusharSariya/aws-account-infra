"""IAM-authenticated subscription administration and explicit read-only sync."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from booker.calendar_repository import CalendarRepository
from booker.secrets import _client_kwargs


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m booker")
    commands = parser.add_subparsers(dest="command", required=True)
    subscription = commands.add_parser("subscription").add_subparsers(
        dest="action", required=True
    )
    create = subscription.add_parser("create")
    create.add_argument("label")
    create.add_argument("--base-url", default=os.environ.get("CALENDAR_BASE_URL"))
    subscription.add_parser("list")
    subscription.add_parser("revoke").add_argument("id")
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


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "subscription" and args.action == "create":
        base = urlsplit(args.base_url or "")
        if (
            base.scheme != "https"
            or not base.netloc
            or base.query
            or base.fragment
            or base.username
        ):
            parser.error(
                "Set CALENDAR_BASE_URL or --base-url to the HTTPS API endpoint"
            )
    try:
        if args.command == "calendar":
            client = boto3.client(
                "lambda",
                **_client_kwargs(),
                config=Config(
                    connect_timeout=5,
                    read_timeout=290,
                    retries={"total_max_attempts": 1, "mode": "standard"},
                ),
            )
            print(json.dumps(sync(client), sort_keys=True))
            return 0
        repository = CalendarRepository()
        if args.action == "create":
            result = repository.create_subscription(args.label)
            print(f"Subscription {result['id']}: {result['label']}")
            print(
                f"{args.base_url.rstrip('/')}/calendars/{result['token']}/bookings.ics"
            )
        elif args.action == "list":
            # Explicit allowlist prevents accidental token disclosure if storage changes.
            print(
                json.dumps(
                    [
                        {
                            key: item[key]
                            for key in (
                                "id",
                                "label",
                                "created_at",
                                "revoked_at",
                                "revoked",
                            )
                            if key in item
                        }
                        for item in repository.list_subscriptions()
                    ],
                    indent=2,
                )
            )
        elif not repository.revoke_subscription(args.id):
            print("Subscription not found", file=sys.stderr)
            return 1
        else:
            print("Subscription revoked")
    except (BotoCoreError, ClientError, RuntimeError, KeyError, ValueError):
        # Never echo payloads, request URLs or secret-bearing exception strings.
        print(
            "Calendar operation failed; check AWS configuration and reconciliation alerts",
            file=sys.stderr,
        )
        return 1
    return 0
