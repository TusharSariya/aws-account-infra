#!/usr/bin/env bash
# Run both tests and packaging in ARM Linux, including on the x64 CI guest.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
operation=${1:?Usage: lambda-package-arm.sh test|package [tag]}
[[ $operation == test || $operation == package ]]
docker buildx build --platform linux/arm64 --load -t homelab-lambda-arm -f "$root/apps/platform/ci_runner/arm-package/Dockerfile" "$root/apps/platform/ci_runner/arm-package"
arguments=(--rm --user "$(id -u):$(id -g)" -e HOME=/tmp --platform linux/arm64 -v "$root:/workspace" -w /workspace)
for name in GITHUB_ACTIONS AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_REGION AWS_DEFAULT_REGION AWS_ACCOUNT_ID LAMBDA_ZIP_BUCKET LAMBDA_ZIP_PREFIX; do
  [[ -z ${!name+x} ]] || arguments+=(-e "$name")
done
if [[ $operation == test ]]; then
  docker run "${arguments[@]}" homelab-lambda-arm bash -ec 'test "$(uname -m)" = aarch64; uv run --directory apps/lambda/python/3.14/court-booker pytest'
else
  docker run "${arguments[@]}" homelab-lambda-arm bash scripts/lambda-package.sh python/3.14/court-booker "${2:?Explicit artifact tag required}"
fi
