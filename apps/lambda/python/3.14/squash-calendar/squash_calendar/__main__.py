"""IAM-authenticated manual initialization and reconciliation."""

import argparse
import json
import time

import boto3
from botocore.config import Config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["sync"])
    parser.add_argument("--function", default="squash-calendar-sync")
    args = parser.parse_args()
    client = boto3.client(
        "lambda",
        config=Config(
            connect_timeout=5,
            read_timeout=650,
            retries={"total_max_attempts": 1, "mode": "standard"},
        ),
    )
    deadline = time.monotonic() + 700
    while True:
        response = client.invoke(
            FunctionName=args.function, InvocationType="RequestResponse", Payload=b"{}"
        )
        with response["Payload"] as body:
            result = json.loads(body.read())
        if response.get("FunctionError"):
            raise SystemExit("Squash calendar sync failed; inspect service alarms")
        if result.get("status") == "synced":
            break
        if result.get("status") != "busy" or time.monotonic() >= deadline:
            raise SystemExit(
                "Squash calendar sync did not complete before the deadline"
            )
        time.sleep(5)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
