#!/usr/bin/env bash
# Point this repo's git hooks at the committed scripts/git-hooks/ directory.
# Run once per clone. Idempotent.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath scripts/git-hooks
chmod +x scripts/git-hooks/*
echo "✓ core.hooksPath -> scripts/git-hooks (pre-push scanner gate active)"
echo "  bypass a single push with: git push --no-verify"
