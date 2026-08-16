#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: $0 <module-directory> <module-name> <semver> <s3-bucket>" >&2
  exit 2
fi

MODULE_DIR="$1"
MODULE_NAME="$2"
MODULE_VERSION="$3"
MODULE_BUCKET="$4"

if [[ ! -d "$MODULE_DIR" ]]; then
  echo "module directory does not exist: $MODULE_DIR" >&2
  exit 2
fi
if [[ ! "$MODULE_NAME" =~ ^[a-z][a-z0-9_-]*$ ]]; then
  echo "invalid module name: $MODULE_NAME" >&2
  exit 2
fi
if [[ ! "$MODULE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "version must be plain semver, for example 1.2.3" >&2
  exit 2
fi

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT
ARCHIVE="$TEMP_DIR/module.zip"

(cd "$MODULE_DIR" && zip -X -q -r "$ARCHIVE" . -x '.terraform/*' '*.tfstate*' '.DS_Store')
DIGEST="$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')"
KEY="modules/$MODULE_NAME/$MODULE_VERSION/$DIGEST/module.zip"

aws s3api put-object \
  --bucket "$MODULE_BUCKET" \
  --key "$KEY" \
  --body "$ARCHIVE" \
  --if-none-match '*' \
  --checksum-algorithm SHA256 >/dev/null

echo "s3::$MODULE_BUCKET/$KEY"
