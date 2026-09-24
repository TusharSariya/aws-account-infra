"""IAM-authenticated manual initialization and reconciliation."""
import argparse
import json
import boto3
from botocore.config import Config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["sync"])
    parser.add_argument("--function", default="swim-calendar-sync")
    args = parser.parse_args()
    client = boto3.client("lambda", config=Config(connect_timeout=5, read_timeout=650,
                         retries={"total_max_attempts": 1, "mode": "standard"}))
    response = client.invoke(FunctionName=args.function, InvocationType="RequestResponse", Payload=b"{}")
    with response["Payload"] as body:
        result = json.loads(body.read())
    if response.get("FunctionError") or result.get("status") != "synced":
        raise SystemExit("Swimming calendar sync failed; inspect service alarms")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
