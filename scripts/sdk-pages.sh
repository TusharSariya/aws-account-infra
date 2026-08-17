#!/usr/bin/env bash
# Stage Swagger UI + OpenAPI contracts for GitHub Pages or a workflow artifact.
# Usage: ./scripts/sdk-pages.sh [dest]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-"$REPO_ROOT/build/api-docs"}"
SWAGGER_UI_VERSION="${SWAGGER_UI_VERSION:-5.29.0}"

rm -rf "$DEST"
mkdir -p "$DEST/specs"

cp "$REPO_ROOT/docs/api/index.html" "$DEST/index.html"
cp -R "$REPO_ROOT/contracts/openapi/." "$DEST/specs/"

python3 - <<PY
from pathlib import Path
import json
dest = Path("$DEST")
urls = []
for spec in sorted((dest / "specs").glob("*/openapi.yaml")):
    urls.append({"url": f"./specs/{spec.parent.name}/openapi.yaml", "name": spec.parent.name})
if not urls:
    raise SystemExit("no contracts/openapi/*/openapi.yaml to publish")
(dest / "urls.js").write_text("window.SPEC_URLS = " + json.dumps(urls) + ";\n")
print("urls:", ", ".join(u["name"] for u in urls))
PY

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
npm pack "swagger-ui-dist@$SWAGGER_UI_VERSION" --pack-destination "$tmp" >/dev/null
tar -xzf "$tmp"/swagger-ui-dist-*.tgz -C "$tmp"
for f in swagger-ui.css swagger-ui-bundle.js swagger-ui-standalone-preset.js; do
  cp "$tmp/package/$f" "$DEST/$f"
done

echo "staged $DEST"
