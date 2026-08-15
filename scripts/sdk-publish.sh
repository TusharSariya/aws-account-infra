#!/usr/bin/env bash
# Publish a generated SDK to CodeArtifact sdk-candidate or sdk-stable.
# Usage: ./scripts/sdk-publish.sh <spec> <target> <candidate|stable>
# Requires AWS credentials. Run sdk-generate.sh first.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SPEC="${1:?usage: $0 <spec> <target> <candidate|stable>}"
TARGET="${2:?usage: $0 <spec> <target> <candidate|stable>}"
CHANNEL="${3:?usage: $0 <spec> <target> <candidate|stable>}"
OUT="$REPO_ROOT/generated/$SPEC/$TARGET"

DOMAIN="${CODEARTIFACT_DOMAIN:-aws-account-infra}"
OWNER="${CODEARTIFACT_DOMAIN_OWNER:-992382747916}"
REGION="${AWS_REGION:-us-east-1}"

case "$CHANNEL" in
  candidate) REPO="sdk-candidate" ;;
  stable) REPO="sdk-stable" ;;
  *)
    echo "channel must be candidate or stable" >&2
    exit 2
    ;;
esac

if [[ ! -d "$OUT" ]]; then
  echo "missing generated tree: $OUT (run sdk-generate.sh first)" >&2
  exit 2
fi

if ! aws codeartifact describe-domain --domain "$DOMAIN" --domain-owner "$OWNER" --region "$REGION" >/dev/null 2>&1; then
  echo "CodeArtifact domain $DOMAIN is not applied yet. Apply aws-staging-account first." >&2
  exit 3
fi

login() {
  aws codeartifact login --tool "$1" --domain "$DOMAIN" --domain-owner "$OWNER" \
    --repository "$REPO" --region "$REGION"
}

case "$TARGET" in
  python)
    login twine
    python3 -m pip install --quiet build twine
    python3 -m build --outdir "$OUT/dist" "$OUT"
    python3 -m twine upload --repository codeartifact --non-interactive "$OUT/dist"/*
    ;;
  typescript-fetch)
    login npm
    (
      cd "$OUT"
      npm install
      npm publish
    )
    ;;
  *)
    echo "unsupported target: $TARGET" >&2
    exit 2
    ;;
esac

echo "published $SPEC/$TARGET -> $REPO"
