#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TERRAFORM_DOCS_BIN="${TERRAFORM_DOCS:-terraform-docs}"
EXPECTED_VERSION="0.24.0"
MODE="${1:-generate}"

if [[ "$MODE" != "generate" && "$MODE" != "--check" ]]; then
  echo "usage: scripts/terraform-docs.sh [generate|--check]" >&2
  exit 2
fi
if ! command -v "$TERRAFORM_DOCS_BIN" >/dev/null 2>&1 && [[ ! -x "$TERRAFORM_DOCS_BIN" ]]; then
  echo "terraform-docs $EXPECTED_VERSION is required" >&2
  exit 2
fi
actual_version="$($TERRAFORM_DOCS_BIN --version | sed -E 's/^terraform-docs version v?([^ ]+).*/\1/')"
if [[ "$actual_version" != "$EXPECTED_VERSION" ]]; then
  echo "terraform-docs $EXPECTED_VERSION required, found $actual_version" >&2
  exit 2
fi

mapfile_compat() {
  while IFS= read -r line; do MODULES+=("$line"); done
}
MODULES=()
mapfile_compat < <(find "$ROOT/modules" -mindepth 2 -maxdepth 2 -type d | sort)

for module in "${MODULES[@]}"; do
  if [[ "$MODE" == "generate" ]]; then
    "$TERRAFORM_DOCS_BIN" --config "$ROOT/.terraform-docs.yml" "$module" >/dev/null
    continue
  fi
  scratch="$(mktemp -d)"
  trap 'rm -rf "$scratch"' EXIT
  cp -R "$module/." "$scratch/"
  "$TERRAFORM_DOCS_BIN" --config "$ROOT/.terraform-docs.yml" "$scratch" >/dev/null
  if ! cmp -s "$module/README.md" "$scratch/README.md"; then
    echo "stale terraform-docs output: ${module#"$ROOT"/}/README.md" >&2
    diff -u "$module/README.md" "$scratch/README.md" || true
    exit 1
  fi
  rm -rf "$scratch"
  trap - EXIT
done

echo "terraform-docs ${MODE#--} valid for ${#MODULES[@]} modules"
