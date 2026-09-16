#!/usr/bin/env bash
# Configure reads only inside a disposable Talos runner.
set -euo pipefail
[[ "${RUNNER_ENVIRONMENT:-}" == self-hosted ]]
[[ "${RUNNER_OS:-}" == Linux ]]
root=$(cd "$(dirname "$0")/.." && pwd)
cache_dir="$RUNNER_TEMP/dependency-transport"
mkdir -p "$cache_dir"
chmod 700 "$cache_dir"
base=http://127.0.0.1:18082
if ! curl --silent --fail --max-time 1 "$base/health" >/dev/null; then
  nohup python3 "$root/scripts/cache_transport.py" --receipts "$cache_dir/reads.jsonl" \
    > "$cache_dir/server.log" 2>&1 < /dev/null &
  echo "$!" > "$cache_dir/pid"
fi
for attempt in {1..20}; do
  if curl --silent --fail --max-time 1 "$base/health" >/dev/null; then break; fi
  if (( attempt == 20 )); then echo "Dependency transport failed to start" >&2; exit 1; fi
  sleep 0.1
done
curl --silent --fail --max-time 1 "$base/health" >/dev/null
# The proxy buffers complete artifacts before replying, so cold large downloads
# need a longer client read timeout. Retry counts remain unchanged.
# A user configuration allows a later CodeArtifact login to replace the registry
# for private reads/publication. Never force a registry through npm's environment.
printf 'registry=%s/npm/\nfetch-retries=0\nfetch-timeout=300000\naudit=false\n' "$base" > "$cache_dir/npmrc"
mkdir -p "$HOME/.config/pip"
# These are fresh disposable runners; a pre-existing config needs explicit review.
test ! -e "$HOME/.config/pip/pip.conf"
printf '[global]\nindex-url = %s/pypi/simple/\nretries = 0\ntimeout = 300\n' "$base" > "$HOME/.config/pip/pip.conf"
{
  printf 'NPM_CONFIG_USERCONFIG=%s/npmrc\n' "$cache_dir"
  printf 'UV_INDEX_URL=%s/pypi/simple/\nUV_HTTP_RETRIES=0\nUV_HTTP_TIMEOUT=300\n' "$base"
  printf 'GOPROXY=%s/go/\n' "$base"
} >> "$GITHUB_ENV"
# Keep every suite, component and Signed-By field intact. Nexus serves the
# reviewed Ubuntu updates/backports suites through the existing APT proxy.
sudo python3 - "$base" <<'PY'
from pathlib import Path
import sys
base = sys.argv[1]
origins = {
    'archive.ubuntu.com/ubuntu': 'apt-ubuntu',
    'ppa.launchpadcontent.net/git-core/ppa/ubuntu': 'apt-git-core',
    'security.ubuntu.com/ubuntu': 'apt-ubuntu-security',
    'deb.debian.org/debian': 'apt-debian',
    'security.debian.org/debian-security': 'apt-debian-security',
}
paths = [Path('/etc/apt/sources.list'), *Path('/etc/apt/sources.list.d').glob('*.list'),
         *Path('/etc/apt/sources.list.d').glob('*.sources')]
for path in paths:
    if not path.exists():
        continue
    text = path.read_text()
    for origin, repository in origins.items():
        for scheme in ('https', 'http'):
            text = text.replace(scheme + '://' + origin, base + '/' + repository)
    path.write_text(text)
Path('/etc/apt/apt.conf.d/99-homelab-cache').write_text('Acquire::Retries "0";\nAcquire::http::Timeout "300";\n')
PY
