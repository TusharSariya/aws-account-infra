#!/usr/bin/env bash
# Build and push apps/ecr/<name> as linux/arm64 to ECR.
# Usage: ./scripts/ecr-image.sh <name> [tag]
# Tag defaults to the short git sha. CI uses the same flags.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="${1:?usage: $0 <name> [tag]}"
TAG="${2:-$(git -C "$REPO_ROOT" rev-parse --short HEAD)}"
CONTEXT="${REPO_ROOT}/apps/ecr/${NAME}"
ACCOUNT="${AWS_ACCOUNT_ID:-992382747916}"
REGION="${AWS_REGION:-us-east-1}"
URI="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${NAME}"

if [[ ! -f "${CONTEXT}/Dockerfile" ]]; then
  echo "no Dockerfile at ${CONTEXT}" >&2
  exit 1
fi

if [[ -z "${GITHUB_ACTIONS:-}" ]]; then
  export AWS_PROFILE="${AWS_PROFILE:-admin}"
fi

aws ecr describe-repositories --repository-names "$NAME" --region "$REGION" >/dev/null 2>&1 \
  || aws ecr create-repository \
    --repository-name "$NAME" \
    --image-tag-mutability IMMUTABLE \
    --image-scanning-configuration scanOnPush=true \
    --region "$REGION" >/dev/null

aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

docker buildx build \
  --platform linux/arm64 \
  --provenance=false \
  --sbom=false \
  -t "${URI}:${TAG}" \
  --push \
  "$CONTEXT"

echo "Pushed ${URI}:${TAG}"
