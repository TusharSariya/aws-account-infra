#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <s3-bucket> <modules/name/version/sha256/module.zip>" >&2
  exit 2
fi

MODULE_BUCKET="$1"
MODULE_KEY="$2"
EXPECTED="$(awk -F/ '{print $(NF-1)}' <<<"$MODULE_KEY")"

if [[ ! "$EXPECTED" =~ ^[0-9a-f]{64}$ ]]; then
  echo "module key does not contain a SHA-256 digest: $MODULE_KEY" >&2
  exit 2
fi

TEMP_ARCHIVE="$(mktemp)"
trap 'rm -f "$TEMP_ARCHIVE"' EXIT
aws s3api get-object --bucket "$MODULE_BUCKET" --key "$MODULE_KEY" "$TEMP_ARCHIVE" >/dev/null
ACTUAL="$(shasum -a 256 "$TEMP_ARCHIVE" | awk '{print $1}')"

if [[ "$ACTUAL" != "$EXPECTED" ]]; then
  echo "module checksum mismatch: expected $EXPECTED, got $ACTUAL" >&2
  exit 1
fi

echo "$ACTUAL"
