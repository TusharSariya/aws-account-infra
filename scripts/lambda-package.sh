#!/usr/bin/env bash
# Build an arm64 Lambda zip from apps/lambda/python/<runtime>/<name> with uv
# and upload it to lambda-releases. Usage:
#   LAMBDA_ZIP_PREFIX=stable/court-booker ./scripts/lambda-package.sh python/3.14/court-booker [tag]
# Tag defaults to the full git sha (same as CI). Does not retarget Lambda.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REL="${1:?usage: $0 python/<runtime>/<name> [tag]}"
if [[ $# -lt 2 && -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
  echo "working tree is dirty; pass an explicit upload tag so we do not overwrite a commit sha zip" >&2
  exit 1
fi
TAG="${2:-$(git -C "$REPO_ROOT" rev-parse HEAD)}"
SHORT="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
SRC="${REPO_ROOT}/apps/lambda/${REL}"
ACCOUNT="${AWS_ACCOUNT_ID:-992382747916}"
REGION="${AWS_REGION:-us-east-1}"
BUCKET="${LAMBDA_ZIP_BUCKET:-lambda-releases-${ACCOUNT}-${REGION}}"
KEY_PREFIX="${LAMBDA_ZIP_PREFIX:-stable/court-booker}"
PY="${LAMBDA_PYTHON:-3.14}"
# Amazon Linux 2023 (python3.14 runtime). Forces linux wheels when packaging on macOS.
PLATFORM="${LAMBDA_PYTHON_PLATFORM:-aarch64-manylinux_2_28}"

ARCH="$(uname -m)"
if [[ "$ARCH" != "arm64" && "$ARCH" != "aarch64" ]]; then
  echo "Lambda is arm64; package on an arm64 host (got ${ARCH})" >&2
  exit 1
fi

if [[ ! -f "${SRC}/pyproject.toml" ]]; then
  echo "missing ${SRC}/pyproject.toml" >&2
  exit 1
fi
if [[ ! -d "${SRC}/booker" ]]; then
  echo "missing ${SRC}/booker (HTTP package lives in the lambda app, not apps/ecr)" >&2
  exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to package Lambda zips" >&2
  exit 1
fi

if [[ -z "${GITHUB_ACTIONS:-}" ]]; then
  export AWS_PROFILE="${AWS_PROFILE:-admin}"
fi

STAGE="${REPO_ROOT}/build/lambda/${REL}"
rm -rf "$STAGE"
mkdir -p "$STAGE"

uv python install "$PY"

REQS="$(mktemp)"
trap 'rm -f "$REQS"' EXIT
uv export --directory "$SRC" --frozen --no-dev --no-hashes --no-annotate --no-header -o "$REQS"

uv pip install --python "$PY" --python-version "$PY" --python-platform "$PLATFORM" \
  --only-binary :all: --no-cache --target "$STAGE" -r "$REQS"

# Generate and vendor the private client into the deployment artifact. This keeps
# application packaging independent of a cross-account CodeArtifact token.
"$REPO_ROOT/scripts/sdk-generate.sh" upace python 0.1.0
uv pip install --python "$PY" --python-version "$PY" --python-platform "$PLATFORM" \
  --no-cache --target "$STAGE" "$REPO_ROOT/generated/upace/python"

# App source last so it wins over any similarly named files from wheels.
cp -R "${SRC}/booker" "${STAGE}/booker"
rm -rf "${STAGE}/booker/__pycache__"
# Shared schedule file — OpenTofu also reads this path.
cp "${REPO_ROOT}/apps/ecr/court-booker/bookings.yaml" "${STAGE}/bookings.yaml"

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

if [[ "${LAMBDA_SKIP_UPLOAD:-false}" == "true" ]]; then
  echo "$ZIP" >"${REPO_ROOT}/build/lambda/package-path.txt"
  echo "Built $ZIP"
  exit 0
fi

aws s3 cp "$ZIP" "s3://${BUCKET}/${KEY_PREFIX}/${TAG}.zip" --region "$REGION"
echo "Uploaded s3://${BUCKET}/${KEY_PREFIX}/${TAG}.zip"
echo "Apply with: ./scripts/infra.sh aws-staging-court-booker-api apply -var booker_api_zip_key=${KEY_PREFIX}/${TAG}.zip"
