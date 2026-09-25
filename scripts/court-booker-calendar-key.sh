#!/usr/bin/env bash
# Generate (or rotate) the court-booker private calendar key and print the
# private calendar URL once. The key is written to an existing SSM
# SecureString parameter created by OpenTofu (value "UNSET" until this runs).
# Rotation = rerun; the old URL stops working within about five minutes as
# warm feed containers refresh their cached key.
#
# Usage: scripts/court-booker-calendar-key.sh [https://API_ID.execute-api.REGION.amazonaws.com]
# Without an argument the endpoint is looked up by API name.
set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-admin}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
PARAMETER="${CALENDAR_PRIVATE_KEY_PARAMETER:-/staging/court-booker-api/calendar-private-key}"
API_NAME="court-booker-api-calendar"

base_url="${1:-}"
if [[ -z "$base_url" ]]; then
  base_url="$(aws apigatewayv2 get-apis \
    --query "Items[?Name=='${API_NAME}'].ApiEndpoint | [0]" --output text)"
fi
base_url="${base_url%/}"
if [[ ! "$base_url" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?$ ]]; then
  echo "Could not determine the calendar API endpoint; pass it as the first argument" >&2
  exit 2
fi

found="$(aws ssm describe-parameters \
  --parameter-filters "Key=Name,Option=Equals,Values=${PARAMETER}" \
  --query 'length(Parameters)' --output text)"
if [[ "$found" != "1" ]]; then
  echo "Parameter ${PARAMETER} does not exist; apply aws-staging-court-booker-api first" >&2
  exit 2
fi

# 32 random bytes, URL-safe base64 without padding (43 characters).
key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
if [[ ${#key} -lt 32 ]]; then
  echo "Key generation failed" >&2
  exit 1
fi

# Pass the value through a private temp file so it never appears in process
# arguments. (file:///dev/stdin reads as empty with the AWS CLI on macOS.)
umask 077
input="$(mktemp)"
trap 'rm -f "$input"' EXIT
KEY="$key" PARAMETER="$PARAMETER" python3 -c '
import json, os
print(json.dumps({
    "Name": os.environ["PARAMETER"],
    "Value": os.environ["KEY"],
    "Type": "SecureString",
    "KeyId": "alias/aws/ssm",
    "Overwrite": True,
    "Tier": "Standard",
}))
' >"$input"
aws ssm put-parameter --cli-input-json "file://${input}" \
  --query 'Version' --output text >/dev/null

echo "Private calendar URL (shown once; store it like a password):" >&2
printf '%s/calendars/private/%s/bookings.ics\n' "$base_url" "$key"
