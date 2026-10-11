"""Operator commands. Secret values never appear in arguments or output."""

import argparse
import getpass
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .api import Zwift
from .auth import CREDENTIALS, TOKENS, Auth
from .service import refresh
from .storage import Parameters, Store, client
from .transport import Transport


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("credentials", help="Prompt and write credentials to SSM")
    commands.add_parser(
        "auth-check", help="Verify login and retrieve current/30-day scores"
    )
    preview = commands.add_parser("preview", help="Write ICS without publishing")
    preview.add_argument("--output-dir", type=Path, required=True)
    sync = commands.add_parser(
        "sync", help="Synchronously invoke the deployed sync function"
    )
    sync.add_argument("--function", default="zwift-calendar-sync")
    history = commands.add_parser("backfill", help="Run one budgeted historical batch")
    history.add_argument("--function", default="zwift-calendar-history")
    commands.add_parser(
        "backfill-status", help="Read private historical coverage and usage"
    )
    bootstrap = commands.add_parser(
        "backfill-all", help="Start the bounded one-off AWS historical workflow"
    )
    bootstrap.add_argument("--state-machine", required=True)
    args = parser.parse_args()
    try:
        if args.command == "credentials":
            parameters = Parameters()
            username = input("Zwift email: ").strip()
            password = getpass.getpass("Zwift password: ")
            if not username or not password:
                raise ValueError("Credentials must not be empty")
            parameters.write(
                os.environ.get("ZWIFT_CREDENTIALS_PARAMETER", CREDENTIALS),
                {"username": username, "password": password},
            )
            parameters.write(os.environ.get("ZWIFT_TOKENS_PARAMETER", TOKENS), {})
            print("Credentials saved; token cache invalidated.")
        elif args.command == "backfill-all":
            response = client("stepfunctions").start_execution(
                stateMachineArn=args.state_machine, input="{}"
            )
            print(json.dumps({"execution_arn": response["executionArn"]}))
        elif args.command == "backfill-status":
            from .backfill import STATE, TARGETS, status
            from .bootstrap import progress

            store = Store()
            state, _ = store.read(STATE)
            target, _ = store.read(TARGETS)
            report = status(state, target)
            report["turnout"] = progress(state, target, datetime.now(UTC))
            report["bootstrap"] = {
                k: v for k, v in state.get("bootstrap", {}).items() if k != "target"
            }
            print(json.dumps(report, indent=2))
        elif args.command in ("sync", "backfill"):
            response = client("lambda").invoke(
                FunctionName=args.function,
                InvocationType="RequestResponse",
                Payload=b"{}",
            )
            with response["Payload"] as body:
                result = json.load(body)
            accepted = (
                {"ok"}
                if args.command == "sync"
                else {"ok", "busy", "no_targets", "budget_limited", "deferred"}
            )
            if response.get("FunctionError") or result.get("status") not in accepted:
                raise RuntimeError("Deployed sync failed")
            print(json.dumps(result))
        elif args.command == "preview":
            result = refresh(
                Store(), Parameters(), Transport(), datetime.now(UTC), preview=True
            )
            if result["status"] == "busy":
                raise RuntimeError("A sync is already running")
            args.output_dir.mkdir(parents=True, exist_ok=True)
            for key, feed in result.pop("calendars").items():
                (args.output_dir / f"zwift-{key}.ics").write_text(feed["ics"])
            print(json.dumps(result, indent=2))
        else:
            store = Store()
            store.claim()
            try:
                http = Transport()
                token = Auth(http, Parameters(), store).access()
                profile = Zwift(http, token).profile(datetime.now(UTC))
                print(
                    json.dumps(
                        {k: profile[k] for k in ("current", "max30", "retrieved_at")}
                    )
                )
            finally:
                store.release()
    except Exception:  # noqa: BLE001 - redact SDK and authentication payloads
        print(
            "Operation failed; verify credentials, permissions, and upstream availability."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
