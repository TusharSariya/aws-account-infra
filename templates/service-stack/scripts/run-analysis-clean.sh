#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--" || $# -lt 2 ]]; then
  echo "usage: $0 -- <repowise-or-graphify-command> [args...]" >&2
  exit 2
fi
shift

before="$(git status --porcelain=v1 --untracked-files=all)"
"$@"
after="$(git status --porcelain=v1 --untracked-files=all)"

if [[ "$before" != "$after" ]]; then
  echo "analysis command changed the worktree; inspect and remove generated files" >&2
  exit 1
fi
