#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <existing-empty-template-repository-directory>" >&2
  exit 2
fi

target="$1"
if [[ ! -d "$target/.git" ]]; then
  echo "target must be an existing Git working tree" >&2
  exit 2
fi
if [[ -n "$(git -C "$target" status --porcelain=v1 --untracked-files=all)" ]]; then
  echo "target working tree must be clean" >&2
  exit 2
fi
if find "$target" -mindepth 1 -maxdepth 1 ! -name .git -print -quit | grep -q .; then
  echo "target repository must be empty before its first seed" >&2
  exit 2
fi

cp -R "$(git rev-parse --show-toplevel)/templates/service-stack/." "$target/"
python3 "$target/scripts/check_repo_contract.py"
echo "template files seeded locally; review, commit, and push them through the protected workflow"
