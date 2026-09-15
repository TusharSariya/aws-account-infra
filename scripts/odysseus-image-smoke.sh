#!/usr/bin/env bash
# Disposable CI fixture: authentication, boot and persistence paths, not model acceptance.
set -euo pipefail
[[ $# == 1 && $1 == ghcr.io/tusharsariyaorg/homelab-odysseus@sha256:* ]] || exit 2
image=$1
network=odysseus-image-smoke
fixture=$(mktemp -d)
chmod 755 "$fixture"
printf %s disposable-fixture-source-------------------------------------------------- > "$fixture/lifecycle-token"
printf %s disposable-fixture-workspace----------------------------------------------- > "$fixture/model-workspace-token"
chmod 644 "$fixture"/*
cp scripts/odysseus-smoke-controller.py "$fixture/server.py"
cleanup() {
  result=$?
  trap - EXIT
  if [[ "$result" != 0 ]]; then docker logs odysseus-smoke 2>&1 | tail -80 || true; fi
  docker rm -f odysseus-smoke chromadb odysseus-smoke-controller >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  rm -rf -- "$fixture"
  exit "$result"
}
trap cleanup EXIT
# Resolve fixture aliases before inherited Kubernetes search domains.
docker network create "$network" >/dev/null
docker run -d --dns-option ndots:0 --name odysseus-smoke-controller --network "$network" \
  --network-alias ai-lifecycle.homelab-platform.svc --user 1000:1000 --cap-drop ALL \
  --security-opt no-new-privileges --read-only --memory 128m -v "$fixture:/fixture:ro" \
  python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 \
  python /fixture/server.py >/dev/null
docker run -d --dns-option ndots:0 --name chromadb --network "$network" --user 1000:1000 \
  --read-only --tmpfs /data:uid=1000,gid=1000 --tmpfs /tmp:uid=1000,gid=1000 \
  -e CHROMA_PERSIST_PATH=/data \
  chromadb/chroma:1.5.5@sha256:0771874eaffc80fb4a66ba4de41a8fadf0447240b08d92353450e26ee43c9355 run --path /data --host 0.0.0.0 --port 8000 >/dev/null
docker run -d --dns-option ndots:0 --name odysseus-smoke --network "$network" --user 1000:1000 \
  --cap-drop ALL --security-opt no-new-privileges --memory 4g \
  -v "$fixture:/credentials:ro" -e POD_UID=disposable-workspace \
  -e HOMELAB_LIFECYCLE_URL=http://ai-lifecycle.homelab-platform.svc:8080 \
  --tmpfs /workspace:uid=1000,gid=1000 --tmpfs /tmp:uid=1000,gid=1000 \
  -p 127.0.0.1:17000:7000 -e AUTH_ENABLED=true -e LOCALHOST_BYPASS=false -e SECURE_COOKIES=false \
  -e ODYSSEUS_ADMIN_USER=admin -e ODYSSEUS_ADMIN_PASSWORD=disposable-ci-fixture-only-password \
  -e ODYSSEUS_DATA_DIR=/workspace/data -e CHROMADB_HOST=chromadb -e CHROMADB_PORT=8000 \
  -e FASTEMBED_CACHE_PATH=/workspace/cache/fastembed "$image" >/dev/null
ready=false
for _ in $(seq 1 90); do
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
docker exec -i odysseus-smoke-controller python - <<'PYTEST'
import http.cookiejar, json, time, urllib.request
base = 'http://odysseus-smoke:7000'
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
request = urllib.request.Request(base + '/api/auth/login',
    data=json.dumps({'username': 'admin', 'password': 'disposable-ci-fixture-only-password'}).encode(),
    headers={'Content-Type': 'application/json'})
assert json.load(client.open(request, timeout=10))['ok']
assert client.open(base + '/api/conversations/topics', timeout=10).status == 200
for _ in range(20):
    calls = json.load(urllib.request.urlopen('http://localhost:8080', timeout=2))
    if '/activity/odysseus/finish' in calls:
        break
    time.sleep(.5)
assert calls.count('/activity/odysseus/begin') == 1, calls
assert calls.count('/activity/odysseus/finish') == 1, calls
assert '/activity/odysseus/heartbeat' in calls
print('PASS: authenticated workspace request admitted and retired; health and login remain passive')
PYTEST
printf 'PASS: non-root image boots, seeds persistent state and rejects unauthenticated API access.\n'
