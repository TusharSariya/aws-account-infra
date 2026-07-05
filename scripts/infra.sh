#!/usr/bin/env bash
# Run an OpenTofu deploy unit declared in deploy-units.json.
# Usage: ./scripts/infra.sh <unit-id> <tofu-subcommand> [arguments...]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <unit-id> <tofu-subcommand> [arguments...]" >&2
  exit 2
fi

UNIT_ID="$1"; shift
SUBCOMMAND="$1"; shift
UNIT_JSON="$(python3 "$REPO_ROOT/scripts/deploy-units.py" get "$UNIT_ID")"
read -r UNIT_PATH VAR_FILE CLOUD < <(python3 -c 'import json,sys; u=json.load(sys.stdin); print(u["path"], u["var_file"], u["cloud"])' <<<"$UNIT_JSON")

if [[ "$CLOUD" == "aws" ]]; then
  export AWS_PROFILE="${AWS_PROFILE:-admin}"
fi

case "$SUBCOMMAND" in
  plan | apply | destroy | refresh | import | console)
    set -- "$SUBCOMMAND" -var-file="$REPO_ROOT/$VAR_FILE" "$@"
    ;;
  *)
    set -- "$SUBCOMMAND" "$@"
    ;;
esac

cd "$REPO_ROOT/$UNIT_PATH"
exec tofu "$@"
