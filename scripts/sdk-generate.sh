#!/usr/bin/env bash
# Generate one SDK from contracts/openapi/<api>/openapi.yaml.
# Usage: ./scripts/sdk-generate.sh <spec> <target> [package-version]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SPEC="${1:?usage: $0 <spec> <target> [package-version]}"
TARGET="${2:?usage: $0 <spec> <target> [package-version]}"
VERSION="${3:-}"

SPEC_FILE="$REPO_ROOT/contracts/openapi/$SPEC/openapi.yaml"
CONFIG="$REPO_ROOT/sdk/targets/$TARGET.yaml"
OUT="$REPO_ROOT/generated/$SPEC/$TARGET"
IMAGE="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["image"])' <"$REPO_ROOT/sdk/openapitools.json")"

if [[ ! -f "$SPEC_FILE" ]]; then
  echo "missing spec: $SPEC_FILE" >&2
  exit 2
fi
if [[ ! -f "$CONFIG" ]]; then
  echo "missing target config: $CONFIG" >&2
  exit 2
fi

if [[ -z "$VERSION" ]]; then
  VERSION="$(python3 "$REPO_ROOT/scripts/sdk-version.py" "$SPEC")"
fi

rm -rf "$OUT"
mkdir -p "$OUT"

ADDITIONAL=("packageVersion=$VERSION" "npmVersion=$VERSION")

docker run --rm \
  -v "$REPO_ROOT:/local" \
  -w /local \
  "$IMAGE" generate \
  -c "/local/sdk/targets/$TARGET.yaml" \
  -i "/local/contracts/openapi/$SPEC/openapi.yaml" \
  -o "/local/generated/$SPEC/$TARGET" \
  --additional-properties="$(IFS=,; echo "${ADDITIONAL[*]}")"

echo "generated $OUT version=$VERSION"
