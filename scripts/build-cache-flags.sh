#!/usr/bin/env bash
# Source immediately before buildx; release --push and its exit status stay owned
# by the caller. Only disposable cache export has ignore-error=true.
build_cache_args=()
if [[ "${HOMELAB_DEPENDENCY_CACHE:-}" == 1 ]]; then
  cache_source_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
  while IFS= read -r -d '' cache_argument; do
    build_cache_args+=("$cache_argument")
  done < <(python3 - "$cache_source_root" <<'PY'
import os, sys
sys.path.insert(0, sys.argv[1] + '/scripts')
from build_cache import settings
value = settings(os.environ['HOMELAB_BUILD_CACHE_WORKFLOW'],
                 os.environ['HOMELAB_BUILD_CACHE_PLATFORM'],
                 os.environ['HOMELAB_BUILD_CACHE_BRANCH'])
arguments = []
for source in value['cache-from'].splitlines():
    arguments.extend(['--cache-from', source])
arguments.extend(['--cache-to', value['cache-to']])
for item in arguments:
    sys.stdout.buffer.write(item.encode() + b'\0')
PY
  )
  # A failure in process substitution is not propagated by Bash. Require both
  # imports/export settings before continuing rather than silently omit caching.
  (( ${#build_cache_args[@]} >= 4 )) || return 1
  build_cache_args+=(--allow network.host --network host
    --secret "id=dependency-env,src=$RUNNER_TEMP/homelab-dependency.env"
    --secret "id=dependency-apt,src=$RUNNER_TEMP/homelab-dependency.apt")
fi
