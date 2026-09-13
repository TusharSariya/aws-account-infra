#!/usr/bin/env bash
# Disposable CI fixture: authentication, boot and persistence paths, not model acceptance.
set -euo pipefail
[[ $# == 1 && $1 == ghcr.io/tusharsariyaorg/homelab-odysseus@sha256:* ]] || exit 2
image=$1
network=odysseus-image-smoke
cleanup() {
  result=$?
  trap - EXIT
  if [[ "$result" != 0 ]]; then docker logs odysseus-smoke 2>&1 | tail -80 || true; fi
  docker rm -f odysseus-smoke chromadb >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  exit "$result"
}
trap cleanup EXIT
docker network create "$network" >/dev/null
docker run -d --name chromadb --network "$network" --user 1000:1000 \
  --read-only --tmpfs /data:uid=1000,gid=1000 --tmpfs /tmp:uid=1000,gid=1000 \
  -e CHROMA_PERSIST_PATH=/data \
  chromadb/chroma:1.5.5@sha256:0771874eaffc80fb4a66ba4de41a8fadf0447240b08d92353450e26ee43c9355 >/dev/null
docker run -d --name odysseus-smoke --network "$network" --user 1000:1000 \
  --cap-drop ALL --security-opt no-new-privileges --memory 4g \
  --tmpfs /workspace:uid=1000,gid=1000 --tmpfs /tmp:uid=1000,gid=1000 \
  -p 127.0.0.1:17000:7000 -e AUTH_ENABLED=true -e LOCALHOST_BYPASS=false \
  -e ODYSSEUS_ADMIN_USER=admin -e ODYSSEUS_ADMIN_PASSWORD=disposable-ci-fixture-only-password \
  -e ODYSSEUS_DATA_DIR=/workspace/data -e CHROMADB_HOST=chromadb \
  -e FASTEMBED_CACHE_PATH=/workspace/cache/fastembed "$image" >/dev/null
ready=false
for attempt in $(seq 1 90); do
  if curl --fail --silent http://127.0.0.1:17000/api/health >/dev/null; then ready=true; break; fi
  [[ $(docker inspect -f '{{.State.Running}}' odysseus-smoke) == true ]] || break
  sleep 2
done
[[ "$ready" == true ]]
[[ $(curl --silent -o /dev/null -w '%{http_code}' http://127.0.0.1:17000/api/conversations/topics) == 401 ]]
docker exec odysseus-smoke python -c '
from pathlib import Path
assert Path("/app/.env").resolve() == Path("/workspace/config.env")
assert Path("/app/data").resolve() == Path("/workspace/data")
assert Path("/workspace/data/auth.json").is_file()
assert Path("/workspace/data/app.db").is_file()
'
printf 'PASS: non-root image boots, seeds persistent state and rejects unauthenticated API access.\n'
