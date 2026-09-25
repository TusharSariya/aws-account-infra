#!/usr/bin/env bash
# Bootstrap/recovery builds directly from upstream in a minimal credential-free context.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
context=$(mktemp -d)
trap 'rm -rf "$context"' EXIT
cp "$root/apps/containers/ci-runner/Dockerfile" "$context/Dockerfile"
cp "$root/scripts/cache_download.py" "$context/cache_download.py"
# shellcheck source=scripts/build-cache-flags.sh
source "$root/scripts/build-cache-flags.sh"
docker buildx build ${build_cache_args[@]+"${build_cache_args[@]}"} --platform linux/amd64 "$@" "$context"
