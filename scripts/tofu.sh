#!/usr/bin/env bash
# Thin wrapper so every stack is invoked consistently from the repo root.
#
#   ./scripts/tofu.sh <stack-dir> <tofu-subcommand> [args...]
#   ./scripts/tofu.sh account plan
#   ./scripts/tofu.sh stacks/rag apply
#
# - Runs `tofu` inside <stack-dir>.
# - Exports AWS_PROFILE (default: admin) as the source profile for assume-role.
# - Auto-injects -var-file=<repo>/common.tfvars for subcommands that take vars.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VAR_FILE="${REPO_ROOT}/common.tfvars"
export AWS_PROFILE="${AWS_PROFILE:-admin}"

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <stack-dir> <tofu-subcommand> [args...]" >&2
  exit 2
fi

STACK_DIR="$1"; shift
SUBCMD="$1"; shift

# Subcommands that accept -var-file.
case "$SUBCMD" in
  plan | apply | destroy | refresh | import | console)
    set -- "$SUBCMD" -var-file="$VAR_FILE" "$@"
    ;;
  *)
    set -- "$SUBCMD" "$@"
    ;;
esac

cd "${REPO_ROOT}/${STACK_DIR}"
exec tofu "$@"
