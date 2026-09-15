#!/usr/bin/env bash
# Disposable authenticated gateway fixture; does not download or benchmark a model.
set -euo pipefail
[[ $# == 1 ]] || exit 2
image=$1
fixture=$(mktemp -d)
network=ollama-smoke-$$
controller=$network-controller
model=$network-model
cleanup() {
  result=$?
  trap - EXIT
  if [[ "$result" != 0 ]]; then docker logs "$model" 2>&1 | tail -40 || true; fi
  docker rm -f "$model" "$controller" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  rm -rf -- "$fixture"
  exit "$result"
}
trap cleanup EXIT
python3 - "$fixture" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
for filename, label in [('lifecycle-token', 'source'), ('model-user-token', 'user'), ('model-workspace-token', 'workspace')]:
    (root / filename).write_text('disposable-fixture-' + label + '-' * 50)
    (root / filename).chmod(0o644)
(root / 'server.py').write_text('''from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
calls = []
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        if self.headers.get('Authorization') != 'Bearer ' + Path('/fixture/lifecycle-token').read_text():
            self.send_error(401); return
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert body['pod_uid'] == 'disposable-pod'
        calls.append(self.path)
        self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(calls).encode())
HTTPServer(('0.0.0.0',8080),Handler).serve_forever()
''')
(root / 'server.py').chmod(0o644)
PY
chmod 755 "$fixture"
docker network create "$network" >/dev/null
docker run -d --name "$controller" --network "$network" --network-alias ai-lifecycle.homelab-platform.svc \
  --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges --read-only --memory 128m \
  -v "$fixture:/fixture:ro" \
  python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 \
  python /fixture/server.py >/dev/null
docker run -d --name "$model" --network "$network" --network-alias ollama \
  --user 1000:1000 --cap-drop ALL --security-opt no-new-privileges --read-only --memory 512m \
  --tmpfs /tmp:uid=1000,gid=1000,size=128m -v "$fixture:/credentials:ro" \
  -e HOME=/tmp -e OLLAMA_MODELS=/tmp/models -e OLLAMA_HOST=0.0.0.0:11434 \
  -e HOMELAB_LIFECYCLE_URL=http://ai-lifecycle.homelab-platform.svc:8080 -e POD_UID=disposable-pod \
  "$image" serve >/dev/null
docker exec -i "$controller" python - <<'PY'
import json,time,urllib.request,urllib.error
from pathlib import Path
base='http://ollama:11434'
for attempt in range(60):
    try:
        urllib.request.urlopen(base+'/healthz',timeout=2).close();break
    except (OSError,urllib.error.URLError):time.sleep(.5)
else:raise AssertionError('gateway did not start')
try:
    urllib.request.urlopen(base+'/api/version',timeout=2)
    raise AssertionError('unauthenticated model API exposed')
except urllib.error.HTTPError as error:assert error.code==401
headers={'Authorization':'Bearer '+Path('/fixture/model-user-token').read_text()}
assert urllib.request.urlopen(urllib.request.Request(base+'/api/version',headers=headers),timeout=2).status==200
request=urllib.request.Request(base+'/api/generate',headers={**headers,'Content-Type':'application/json'},data=b'{"model":"disposable-model-does-not-exist","prompt":"fixture"}')
try:urllib.request.urlopen(request,timeout=5)
except urllib.error.HTTPError as error:assert error.code==404
for attempt in range(20):
    calls=json.load(urllib.request.urlopen('http://localhost:8080',timeout=2))
    if '/activity/ollama/finish' in calls:break
    time.sleep(.5)
assert calls.count('/activity/ollama/begin')==1
assert calls.count('/activity/ollama/finish')==1
print('PASS: packaged gateway authenticates, admits and retires model API work; health remains passive')
PY
