#!/usr/bin/env bash
set -euo pipefail
network="postgres-test-$(date +%s)-$$"
image=ghcr.io/cloudnative-pg/postgresql:18.4-standard-trixie@sha256:ebf3919504d7523a63e8e2fee9b051211de714644b36469275558c624afd50ec
# dockerd registry mirrors cover docker.io only, so a plain `docker run "$image"`
# re-pulls from ghcr even though BuildKit already fetched it (via the Nexus ghcr
# mirror) for the backup image. CI therefore sets POSTGRES_SERVER_IMAGE to the
# freshly loaded backup image, which is only accepted when it is built FROM this
# exact pinned server image: identical initdb/postgres binaries, no second pull.
server_image=${POSTGRES_SERVER_IMAGE:-$image}
if [[ "$server_image" != "$image" ]] && ! grep -qxF "FROM $image" apps/containers/postgres-backup/Dockerfile; then
  echo "POSTGRES_SERVER_IMAGE requires the backup Dockerfile to be FROM $image" >&2
  exit 1
fi
private=$(mktemp -d)
cleanup() {
  docker rm -f "$network-source" "$network-old" "$network-current" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  rm -rf "$private"
}
trap cleanup EXIT
helm template apps-db charts/homelab-postgres > "$private/render.yaml"
uv run --with PyYAML==6.0.3 python - "$private" <<'PY'
import json,sys,yaml
from pathlib import Path
p=Path(sys.argv[1])
cluster=next(d for d in yaml.safe_load_all((p/'render.yaml').read_text()) if d and d['kind']=='Cluster')
(p/'bootstrap.json').write_text(json.dumps(cluster['spec']['bootstrap']['initdb']['postInitApplicationSQL']))
PY
docker network create --internal "$network" >/dev/null
for name in source old current; do
  docker run -d --platform linux/amd64 --network "$network" --network-alias "$name" --name "$network-$name" \
    --user 26 --entrypoint /bin/bash "$server_image" -c 'initdb -D /tmp/data -A trust --encoding=UTF8 >/dev/null && echo "host all all all trust" >> /tmp/data/pg_hba.conf && exec postgres -D /tmp/data -h "*"' >/dev/null
done
docker run --rm --platform linux/amd64 --network "$network" -e SOURCE_HOST=source -e TARGET_HOSTS=old,current \
  -v "$PWD:/repo:ro" -v "$private/bootstrap.json:/tmp/bootstrap.json:ro" \
  --entrypoint python homelab-postgres-backup:local /repo/scripts/tests/postgres_integration.py
