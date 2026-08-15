#!/usr/bin/env bash
# Build an arm64 Lambda zip from apps/lambda/python/<runtime>/<name> and upload
# it to lambda-releases. Usage:
#   LAMBDA_ZIP_PREFIX=stable/court-booker ./scripts/lambda-package.sh python/3.12/court-booker [tag]
# Tag defaults to the full git sha (same as CI). Does not retarget Lambda.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REL="${1:?usage: $0 python/<runtime>/<name> [tag]}"
TAG="${2:-$(git -C "$REPO_ROOT" rev-parse HEAD)}"
SHORT="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
SRC="${REPO_ROOT}/apps/lambda/${REL}"
ACCOUNT="${AWS_ACCOUNT_ID:-992382747916}"
REGION="${AWS_REGION:-us-east-1}"
DOMAIN="${CODEARTIFACT_DOMAIN:-aws-account-infra}"
OWNER="${CODEARTIFACT_DOMAIN_OWNER:-992382747916}"
BUCKET="${LAMBDA_ZIP_BUCKET:-lambda-releases-${ACCOUNT}-${REGION}}"
KEY_PREFIX="${LAMBDA_ZIP_PREFIX:-stable/court-booker}"

ARCH="$(uname -m)"
if [[ "$ARCH" != "arm64" && "$ARCH" != "aarch64" ]]; then
  echo "Lambda is arm64; package on an arm64 host (got ${ARCH})" >&2
  exit 1
fi

if [[ ! -f "${SRC}/requirements.txt" ]]; then
  echo "missing ${SRC}/requirements.txt" >&2
  exit 1
fi

if [[ -z "${GITHUB_ACTIONS:-}" ]]; then
  export AWS_PROFILE="${AWS_PROFILE:-admin}"
fi

STAGE="${REPO_ROOT}/build/lambda/${REL}"
rm -rf "$STAGE"
mkdir -p "$STAGE"

BOOKER_SRC="${REPO_ROOT}/apps/ecr/court-booker"
cp -R "${BOOKER_SRC}/booker" "${STAGE}/booker"
rm -f "${STAGE}/booker/upace.py"
cp "${BOOKER_SRC}/bookings.yaml" "${STAGE}/bookings.yaml"

python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet --no-cache-dir \
  -r "${SRC}/requirements.txt" \
  --target "$STAGE"

TOKEN="$(aws codeartifact get-authorization-token \
  --domain "$DOMAIN" --domain-owner "$OWNER" --region "$REGION" \
  --query authorizationToken --output text --duration-seconds 900)"
python3 -m pip install --quiet --no-cache-dir \
  "upace==0.1.0" \
  --index-url "https://aws:${TOKEN}@${DOMAIN}-${OWNER}.d.codeartifact.${REGION}.amazonaws.com/pypi/sdk-stable/simple/" \
  --extra-index-url https://pypi.org/simple \
  --target "$STAGE"

find "$STAGE" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$STAGE" -type f -name '*.pyc' -delete

ZIP="${REPO_ROOT}/build/lambda/${KEY_PREFIX}-${SHORT}.zip"
rm -f "$ZIP"
python3 - <<PY
import pathlib
import zipfile

root = pathlib.Path("${STAGE}")
out = pathlib.Path("${ZIP}")
out.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            zf.write(path, path.relative_to(root).as_posix())
PY

aws s3 cp "$ZIP" "s3://${BUCKET}/${KEY_PREFIX}/${TAG}.zip" --region "$REGION"
echo "Uploaded s3://${BUCKET}/${KEY_PREFIX}/${TAG}.zip"
echo "Apply with: ./scripts/infra.sh aws-staging-court-booker-api apply -var booker_api_zip_key=${KEY_PREFIX}/${TAG}.zip"
