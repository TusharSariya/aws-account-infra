#!/usr/bin/env bash
# Upload My Y credentials from repo-root .env into two SSM SecureString
# parameters (one per Lambda). Does not print username or password. Does not
# write them to Terraform.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${1:-$REPO_ROOT/.env}"
export AWS_PROFILE="${AWS_PROFILE:-admin}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE" >&2
  exit 2
fi

python3 - "$ENV_FILE" <<'PY'
import json
import sys
from pathlib import Path

import boto3

env_path = Path(sys.argv[1])
names = ("/staging/court-booker/my-y", "/staging/court-booker-api/my-y")
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

payload = json.dumps(
    {
        "my_YMCA_username": values["my_YMCA_username"],
        "my_YMCA_password": values["my_YMCA_password"],
    },
    separators=(",", ":"),
)
client = boto3.client("ssm")
written = []
for name in names:
    resp = client.put_parameter(
        Name=name,
        Value=payload,
        Type="SecureString",
        KeyId="alias/aws/ssm",
        Overwrite=True,
        Tier="Standard",
    )
    written.append({"Name": name, "Version": resp["Version"], "Tier": resp.get("Tier", "Standard")})
print(json.dumps(written))
PY
