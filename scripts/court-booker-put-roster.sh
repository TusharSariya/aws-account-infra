#!/usr/bin/env bash
# Upload the friend ACK roster to its SSM SecureString parameter.
# Usage: scripts/court-booker-put-roster.sh [roster.json]   (reads stdin when omitted)
#
# Roster JSON maps each bookings.yaml activity to its friends:
#   {"court1": [{"name": "Alex", "email": "alex@example.com"}], "court2": [...]}
# The value is validated locally and sent with --overwrite semantics. Names and
# addresses are never printed, and the value never goes on a command line.
# The parameter is created by OpenTofu once ack_mode != "off"; this script only
# overwrites it and refuses to create it.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-admin}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
PARAMETER_NAME="${ACK_ROSTER_PARAMETER:-/staging/court-booker-api/ack-roster}"
SOURCE="${1:--}"

if [[ "$SOURCE" != "-" && ! -f "$SOURCE" ]]; then
  echo "missing $SOURCE" >&2
  exit 2
fi

# Program via -c so stdin stays free for the roster itself.
PROGRAM="$(cat <<'PY'
import json
import re
import sys
from pathlib import Path

import boto3

source, name = sys.argv[1], sys.argv[2]
raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")

try:
    roster = json.loads(raw)
except json.JSONDecodeError as exc:
    # Report position only; the message would otherwise quote roster content.
    raise SystemExit(f"roster is not valid JSON (line {exc.lineno}, column {exc.colno})")

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
errors = []
if not isinstance(roster, dict) or not roster:
    errors.append("roster must be a non-empty JSON object of activity -> list of friends")
else:
    for activity, friends in roster.items():
        if not isinstance(activity, str) or not activity.strip():
            errors.append("activity names must be non-empty strings")
            continue
        if not isinstance(friends, list):
            errors.append(f"{activity}: value must be a list")
            continue
        seen = set()
        for index, friend in enumerate(friends):
            where = f"{activity}[{index}]"
            if not isinstance(friend, dict) or set(friend) != {"name", "email"}:
                errors.append(f"{where}: must be an object with exactly 'name' and 'email'")
                continue
            if not isinstance(friend["name"], str) or not friend["name"].strip():
                errors.append(f"{where}: name must be a non-empty string")
            email = friend["email"]
            if not isinstance(email, str) or not EMAIL.match(email):
                errors.append(f"{where}: email is not a valid address")
            elif email.lower() in seen:
                errors.append(f"{where}: duplicate email within {activity}")
            else:
                seen.add(email.lower())
if errors:
    raise SystemExit("invalid roster:\n  " + "\n  ".join(errors))

client = boto3.client("ssm")
found = client.describe_parameters(
    ParameterFilters=[{"Key": "Name", "Option": "Equals", "Values": [name]}]
).get("Parameters", [])
if not found:
    raise SystemExit(f"{name} does not exist; apply the court-booker-api unit with ack_mode != \"off\" first")

payload = json.dumps(roster, separators=(",", ":"), ensure_ascii=False)
resp = client.put_parameter(
    Name=name,
    Value=payload,
    Type="SecureString",
    KeyId="alias/aws/ssm",
    Overwrite=True,
    Tier="Standard",
)
print(json.dumps({
    "Name": name,
    "Version": resp["Version"],
    "Friends": {activity: len(friends) for activity, friends in roster.items()},
}))
PY
)"
python3 -c "$PROGRAM" "$SOURCE" "$PARAMETER_NAME"
