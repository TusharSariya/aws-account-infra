#!/usr/bin/env bash
# Private local preview; deployment remains in GitHub CI.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
private=$(mktemp -d "${TMPDIR:-/tmp}/talos-plan.XXXXXXXX")
trap 'rm -rf -- "$private"' EXIT
uv run scripts/talos-ci.py setup
uv run scripts/talos-ci.py prepare --private "$private" --secrets-file "${1:?Pass the original private Talos secrets file}"
uv run scripts/talos-ci.py preflight --private "$private"
uv run scripts/talos-ci.py exec --private "$private" -- tofu -chdir=live/talos/homelab init -input=false -lockfile=readonly
uv run scripts/talos-ci.py exec --private "$private" -- tofu -chdir=live/talos/homelab validate
uv run scripts/talos-ci.py exec --private "$private" -- tofu -chdir=live/talos/homelab plan -input=false -lock-timeout=60s \
  -var-file="$PWD/config/environments/talos/homelab/cluster.tfvars" -out="$private/tfplan"
uv run scripts/talos-ci.py guard --private "$private"
