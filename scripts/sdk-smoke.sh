#!/usr/bin/env bash
# Smoke-test a generated SDK. Usage: ./scripts/sdk-smoke.sh <spec> <target>
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SPEC="${1:?usage: $0 <spec> <target>}"
TARGET="${2:?usage: $0 <spec> <target>}"
OUT="$REPO_ROOT/generated/$SPEC/$TARGET"

if [[ ! -d "$OUT" ]]; then
  echo "missing generated tree: $OUT" >&2
  exit 2
fi

case "$TARGET" in
    python)
    venv="$OUT/.smoke-venv"
    python3 -m venv "$venv"
    "$venv/bin/pip" install --quiet --upgrade pip
    "$venv/bin/pip" install --quiet "$OUT"
    "$venv/bin/python" - <<PY
import upace
from upace import AuthApi, ApiClient, Configuration
print("upace", upace.__version__)
print("AuthApi", AuthApi)
print("ApiClient", ApiClient)
print("Configuration", Configuration)
PY
    ;;
  typescript-fetch)
    (
      cd "$OUT"
      npm install
      node -e "const p=require('./package.json'); if (!p.name) process.exit(1); console.log(p.name, p.version)"
    )
    ;;
  *)
    echo "unsupported target: $TARGET" >&2
    exit 2
    ;;
esac
