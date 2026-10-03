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
    from .auth import Auth, AuthError, Parameters
    from .store import Conflict, Store

    secrets = Parameters(args.client_parameter, args.token_parameter)
    try:
        if args.auth_action == "migrate":
            from .auth_migration import migrate_auth

            result = migrate_auth(
                secrets,
                Store(bucket=args.bucket),
                args.legacy_client_secret,
                args.legacy_token_secret,
            )
            print(json.dumps(result))
            return 0
        if args.auth_action == "status":
            status = secrets.status()
            print(json.dumps(status, indent=2))
            return int(status["reauthentication_required"])
        # Refuse getpass's fallback to echoed stdin. Credentials never enter argv.
        saved = secrets.read(secrets.client_parameter)
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
        previous, etag, owner = store.claim()
        try:
            Auth(secrets, store, etag, owner).bootstrap(
                config, config["allowed_username"], password
            )
            store.publish(
                previous
                | {
                    "auth_storage": {
                        "client": args.client_parameter,
                        "tokens": args.token_parameter,
                    }
                },
                etag,
                owner,
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
    for name in ("bootstrap", "status", "migrate"):
        command = commands.add_parser(name)
        command.add_argument(
            "--client-parameter", required=True, help="SSM SecureString parameter name"
        )
        command.add_argument(
            "--token-parameter",
            required=True,
            help="Separate SSM SecureString parameter name",
        )
        if name in {"bootstrap", "migrate"}:
            command.add_argument(
                "--bucket",
                required=True,
                help="Existing snapshot bucket for the shared lease",
            )
        if name == "migrate":
            command.add_argument("--legacy-client-secret", required=True)
            command.add_argument("--legacy-token-secret", required=True)
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
