#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

usage() {
  cat >&2 <<'EOF'
usage: scripts/repository-intelligence.sh COMMAND [arguments]

Commands:
  repowise-init       Build the ignored, deterministic RepoWise index.
  repowise-update     Refresh only the ignored RepoWise index.
  repowise-status     Query RepoWise status without changing any repository file.
  repowise-risk REV   Query change risk for a revision range without mutations.
  graphify-generate   Generate the ignored Graphify snapshot for review.
  graphify-query Q    Query the reviewed graph without mutations.
  graphify-affected N Run Graphify impact traversal without mutations.
EOF
  exit 2
}

visible_status() {
  git status --porcelain=v1 --untracked-files=all
}

query_snapshot() {
  visible_status
  for directory in .repowise graphify-out; do
    if [[ -d "$directory" ]]; then
      find "$directory" -type f -print0 | sort -z | xargs -0 shasum -a 256
    fi
  done
}

run_generation() {
  local allowed="$1"
  shift
  local before after
  before="$(visible_status)"
  "$@"
  after="$(visible_status)"
  if [[ "$before" != "$after" ]]; then
    echo "$allowed generation changed source outside its ignored output directory" >&2
    diff -u <(printf '%s\n' "$before") <(printf '%s\n' "$after") || true
    exit 1
  fi
}

run_query() {
  local before_file after_file
  before_file="$(mktemp)"
  after_file="$(mktemp)"
  trap 'rm -f "$before_file" "$after_file"' RETURN
  query_snapshot >"$before_file"
  "$@"
  query_snapshot >"$after_file"
  if ! diff -u "$before_file" "$after_file"; then
    echo "repository-intelligence query changed the worktree or an index" >&2
    exit 1
  fi
}

case "${1:-}" in
  repowise-init)
    shift
    run_generation RepoWise env DO_NOT_TRACK=1 REPOWISE_SKIP_EDITOR_SETUP=1 \
      REPOWISE_NO_SAVE_KEY=1 repowise init . --no-prose --no-editor-setup \
      --no-save-key --no-claude-md --no-agents --no-codex --no-distill-hook \
      --no-workspace --yes "$@"
    ;;
  repowise-update)
    shift
    run_generation RepoWise env DO_NOT_TRACK=1 REPOWISE_NO_SAVE_KEY=1 \
      repowise update . --index-only --no-agents --no-workspace "$@"
    ;;
  repowise-status)
    shift
    run_query repowise status . --no-workspace "$@"
    ;;
  repowise-risk)
    [[ $# -ge 2 ]] || usage
    revision="$2"
    shift 2
    run_query repowise risk "$revision" "$@"
    ;;
  graphify-generate)
    shift
    run_generation Graphify graphify extract . "$@"
    ;;
  graphify-query)
    [[ $# -ge 2 ]] || usage
    question="$2"
    shift 2
    run_query graphify query "$question" "$@"
    ;;
  graphify-affected)
    [[ $# -ge 2 ]] || usage
    node="$2"
    shift 2
    run_query graphify affected "$node" "$@"
    ;;
  *) usage ;;
esac
