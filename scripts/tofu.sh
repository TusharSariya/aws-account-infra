#!/usr/bin/env bash
# Compatibility entrypoint. New callers should use scripts/infra.sh with a deploy-unit ID.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$REPO_ROOT/scripts/infra.sh" "$@"
