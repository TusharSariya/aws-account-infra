#!/usr/bin/env bash
# Upload My Y credentials from repo-root .env into Secrets Manager.
# Does not print username or password. Does not write them to Terraform.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${1:-$REPO_ROOT/.env}"
SECRET_ID="staging/court-booker/my-y"
export AWS_PROFILE="${AWS_PROFILE:-admin}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE" >&2
  exit 2
fi

python3 - "$ENV_FILE" "$SECRET_ID" <<'PY'
import json
import sys
from pathlib import Path

import boto3

env_path = Path(sys.argv[1])
secret_id = sys.argv[2]
values: dict[str, str] = {}
for raw in env_path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, value = line.partition("=")
    key = key.strip()
    value = value.strip().strip("'").strip('"')
    if key in {"my_YMCA_username", "my_YMCA_password"}:
        values[key] = value

missing = [k for k in ("my_YMCA_username", "my_YMCA_password") if not values.get(k)]
if missing:
    raise SystemExit(f"missing in {env_path}: {', '.join(missing)}")

client = boto3.client("secretsmanager")
resp = client.put_secret_value(
    SecretId=secret_id,
    SecretString=json.dumps(
        {
            "my_YMCA_username": values["my_YMCA_username"],
            "my_YMCA_password": values["my_YMCA_password"],
        },
        separators=(",", ":"),
    ),
)
print(
    json.dumps(
        {
            "Name": resp["Name"],
            "VersionId": resp["VersionId"],
            "Stages": resp["VersionStages"],
        }
    )
)
PY
