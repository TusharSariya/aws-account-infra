#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/mocks/localstack/compose.yml"
ACTION="${1:-}"

case "$ACTION" in
  up)
    docker compose -f "$COMPOSE_FILE" up -d --wait
    ;;
  down)
    docker compose -f "$COMPOSE_FILE" down
    ;;
  reset)
    docker compose -f "$COMPOSE_FILE" down --volumes
    docker compose -f "$COMPOSE_FILE" up -d --wait
    ;;
  logs)
    docker compose -f "$COMPOSE_FILE" logs -f
    ;;
  smoke)
    "$REPO_ROOT/mocks/localstack/smoke.sh"
    ;;
  *)
    echo "usage: $0 {up|down|reset|logs|smoke}" >&2
    exit 2
    ;;
esac
