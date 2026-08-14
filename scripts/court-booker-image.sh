#!/usr/bin/env bash
# Back-compat wrapper. Prefer: ./scripts/ecr-image.sh court-booker [tag]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${1:-$(git -C "$REPO_ROOT" rev-parse --short HEAD)}"
"$REPO_ROOT/scripts/ecr-image.sh" court-booker "$TAG"
echo "Apply with: ./scripts/infra.sh aws-staging-court-booker apply -var booker_image_tag=${TAG}"
