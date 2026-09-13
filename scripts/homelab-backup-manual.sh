#!/usr/bin/env bash
# Compatibility entry point. Run with bash; never source into your shell.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  printf 'Run this script with bash; do not source it.\n' >&2
  return 1
fi
set -euo pipefail
[[ $# -le 1 ]] || { echo 'Usage: bash scripts/homelab-backup-manual.sh [--etcd]' >&2; exit 1; }
case "${1:-bootstrap}" in
  bootstrap) mode=bootstrap ;;
  --etcd) mode=etcd ;;
  *) echo 'Usage: bash scripts/homelab-backup-manual.sh [--etcd]' >&2; exit 1 ;;
esac
exec python3 "$(dirname "$0")/homelab-backup.py" backup --mode "$mode"
