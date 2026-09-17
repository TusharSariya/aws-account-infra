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

package_version() {
  case "$TARGET" in
    python)
      python3 -c 'import pathlib,re; t=pathlib.Path("'"$OUT"'/pyproject.toml").read_text(); print(re.search(r"^version = \"([^\"]+)\"", t, re.M).group(1))'
      ;;
    typescript-fetch)
      python3 -c 'import json; print(json.load(open("'"$OUT"'/package.json"))["version"])'
      ;;
  esac
}

package_format() {
  case "$TARGET" in
    python) echo pypi ;;
    typescript-fetch) echo npm ;;
  esac
}

package_name() {
  case "$TARGET" in
    python)
      python3 -c 'import pathlib,re; t=pathlib.Path("'"$OUT"'/pyproject.toml").read_text(); print(re.search(r"^name = \"([^\"]+)\"", t, re.M).group(1))'
      ;;
    typescript-fetch)
      python3 -c 'import json; print(json.load(open("'"$OUT"'/package.json"))["name"])'
      ;;
  esac
}

already_published() {
  local name version format
  name="$(package_name)"
  version="$(package_version)"
  format="$(package_format)"
  aws codeartifact describe-package-version \
    --domain "$DOMAIN" --domain-owner "$OWNER" --repository "$REPO" \
    --format "$format" --package "$name" --package-version "$version" \
    --region "$REGION" >/dev/null 2>&1
}

login() {
  aws codeartifact login --tool "$1" --domain "$DOMAIN" --domain-owner "$OWNER" \
    --repository "$REPO" --region "$REGION"
}

if already_published; then
  echo "already in $REPO: $(package_name) $(package_version); skipping"
  exit 0
fi

case "$TARGET" in
  python)
    python3 -m pip install --quiet build twine
    python3 -m build --outdir "$OUT/dist" "$OUT"
    login twine
    python3 -m twine upload --repository codeartifact --non-interactive "$OUT/dist"/*
    ;;
  typescript-fetch)
    # Install build deps from the public registry. CodeArtifact has no npmjs
    # upstream (one repo also holds PyPI packages, one external connection max).
    dependency_registry=https://registry.npmjs.org
    if [[ "${HOMELAB_DEPENDENCY_CACHE:-}" == 1 ]]; then
      dependency_registry=http://127.0.0.1:18082/npm/
    fi
    (cd "$OUT" && npm install --registry "$dependency_registry")
    login npm
    (cd "$OUT" && npm publish --ignore-scripts)
    ;;
  *)
    echo "unsupported target: $TARGET" >&2
    exit 2
    ;;
esac

echo "published $SPEC/$TARGET -> $REPO"
