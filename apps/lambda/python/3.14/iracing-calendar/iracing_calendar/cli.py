"""Read-only live extraction or IAM-authenticated synchronous manual refresh."""

import argparse
import getpass
import json
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path

from botocore.config import Config

from .sources import Fetcher


def auth_command(args):
    from .auth import Auth, AuthError, Secrets
    from .store import Conflict, Store

    secrets = Secrets(args.client_secret, args.token_secret)
    try:
        if args.auth_action == "status":
            status = secrets.status()
            print(json.dumps(status, indent=2))
            return int(status["reauthentication_required"])
        # Refuse getpass's fallback to echoed stdin. Credentials never enter argv.
        saved = secrets.read(secrets.client_secret)
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            config = {
                "client_id": saved.get("client_id")
                or getpass.getpass("Registered client ID: "),
                "client_secret": saved.get("client_secret")
                or getpass.getpass("Registered client secret: "),
                "allowed_username": saved.get("allowed_username")
                or getpass.getpass("Registered allowed username: "),
                "allowed_cust_id": int(
                    saved.get("allowed_cust_id")
                    or getpass.getpass("Allowed iRacing customer ID: ")
                ),
            }
            password = getpass.getpass("iRacing account password (never stored): ")
        store = Store(bucket=args.bucket)
        _, etag, owner = store.claim()
        try:
            Auth(secrets, store, etag, owner).bootstrap(
                config, config["allowed_username"], password
            )
        finally:
            password = None
            store.release(etag, owner)
        print(json.dumps(secrets.status(), indent=2))
        return 0
    except (AuthError, Conflict) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except getpass.GetPassWarning, ValueError:
        print(
            "Authentication unavailable. Check configuration or run local auth bootstrap using a terminal.",
            file=sys.stderr,
        )
        return 1


def main():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command", required=True)
    live = subs.add_parser("extract")
    live.add_argument("--output", type=Path, required=True)
    catalog = subs.add_parser(
        "catalog", help="Read-only official inventory coverage report"
    )
    catalog.add_argument("--year", type=int, required=True)
    sync = subs.add_parser("sync")
    sync.add_argument("--function", required=True)
    auth = subs.add_parser("auth")
    commands = auth.add_subparsers(dest="auth_action", required=True)
    for name in ("bootstrap", "status"):
        command = commands.add_parser(name)
        command.add_argument(
            "--client-secret", required=True, help="Secrets Manager name or ARN"
        )
        command.add_argument(
            "--token-secret", required=True, help="Separate Secrets Manager name or ARN"
        )
        if name == "bootstrap":
            command.add_argument(
                "--bucket",
                required=True,
                help="Existing snapshot bucket for the shared lease",
            )
    args = parser.parse_args()
    if args.command == "auth":
        return auth_command(args)
    if args.command == "catalog":
        from .catalog import SOURCE, coverage_report, load_catalog, parse_inventory

        report = coverage_report(
            load_catalog(args.year), parse_inventory(Fetcher().get(SOURCE), args.year)
        )
        print(json.dumps(report, indent=2))
        return 0 if report["publication_ready"] else 1
    if args.command == "extract":
        from .store import Store
        from .sync import refresh

        snapshot = refresh(Store(), datetime.now(UTC), preview=True)
        if snapshot.get("status") == "busy":
            print("Sync lease is busy; retry later", file=sys.stderr)
            return 1
        args.output.write_text(snapshot["ics"])
        args.output.with_suffix(".json").write_text(json.dumps(snapshot, indent=2))
        print(json.dumps(snapshot["report"], indent=2))
        return 0
    import boto3

    api = boto3.client(
        "lambda",
        config=Config(
            connect_timeout=5, read_timeout=610, retries={"total_max_attempts": 1}
        ),
    )
    response = api.invoke(
        FunctionName=args.function,
        InvocationType="RequestResponse",
        Payload=b'{"action":"sync"}',
    )
    with response["Payload"] as stream:
        result = json.load(stream)
    print(json.dumps(result, indent=2))
    return 1 if response.get("FunctionError") or result.get("status") != "ok" else 0


if __name__ == "__main__":
    raise SystemExit(main())
