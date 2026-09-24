"""Read-only live extraction or IAM-authenticated synchronous manual refresh."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from botocore.config import Config

from .reconcile import reconcile
from .sources import Fetcher, extract


def main():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command", required=True)
    live = subs.add_parser("extract")
    live.add_argument("--output", type=Path, required=True)
    sync = subs.add_parser("sync")
    sync.add_argument("--function", required=True)
    args = parser.parse_args()
    if args.command == "extract":
        events, coverage, _ = extract(Fetcher())
        snapshot = reconcile({}, events, coverage, datetime.now(UTC))
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
