#!/usr/bin/env bash
# Operate the parallel "homelab-operator" GitHub Actions runners that run as Linux
# containers on the owner's Mac (platform/operator-runner/compose.yaml and
# docs/runbooks/mac-operator-runner.md).
#
#   image        pull the ARC runner image at the digest pinned in
#                config/environments/kubernetes/homelab-ci/arc-runner-values.yaml
#                (--build builds it locally from apps/containers/ci-runner instead)
#   register     register every runner once (RUNNER_TOKEN in the environment,
#                RUNNER_GROUP defaults to homelab-operator); containers stay stopped
#   start        start the containers (maintenance window opens)
#   stop         stop the containers (maintenance window closes)
#   status       container state plus each runner's GitHub online/busy status
#   remove       deregister (RUNNER_TOKEN must be a removal token) and delete volumes
#   token-help   print how to obtain registration and removal tokens
#
# RUNNERS (default 3) selects how many of the compose services are used.
# Compatible with macOS /bin/bash 3.2. Never prints RUNNER_TOKEN.
set -euo pipefail

readonly ORG=TusharSariyaOrg
readonly REPO="${ORG}/aws-account-infra"
readonly GROUP_DEFAULT=homelab-operator
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
readonly COMPOSE="$REPO_ROOT/platform/operator-runner/compose.yaml"
readonly VALUES="$REPO_ROOT/config/environments/kubernetes/homelab-ci/arc-runner-values.yaml"
readonly LOCAL_TAG=homelab-ci-runner:operator-local
RUNNERS="${RUNNERS:-3}"

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

info() {
  printf '==> %s\n' "$*"
}

host_name() {
  scutil --get LocalHostName | tr '[:upper:]' '[:lower:]'
}

pinned_image() {
  # The single source of truth is the ARC runner pod template.
  python3 - "$VALUES" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
images = sorted(set(re.findall(r'ghcr\.io/tusharsariyaorg/homelab-ci-runner@sha256:[0-9a-f]{64}', text)))
if len(images) != 1:
    sys.exit('expected exactly one pinned homelab-ci-runner digest in arc-runner-values.yaml')
print(images[0])
PY
}

check_prerequisites() {
  [[ "$(uname -s)" == Darwin ]] || die 'the container operator runners are designed for the owner Mac'
  command -v docker > /dev/null || die 'docker CLI missing (OrbStack or Docker Desktop)'
  docker compose version > /dev/null 2>&1 || die 'docker compose plugin missing'
  docker info > /dev/null 2>&1 || die 'docker engine not running (start OrbStack)'
  command -v gh > /dev/null || die 'gh missing (brew install gh)'
  command -v python3 > /dev/null || die 'python3 missing'
  [[ "$RUNNERS" =~ ^[1-3]$ ]] || die 'RUNNERS must be 1, 2 or 3 (compose.yaml declares three services)'
}

services() {
  local i=1
  while (( i <= RUNNERS )); do
    printf 'runner-%d ' "$i"
    i=$((i + 1))
  done
}

compose() {
  OPERATOR_RUNNER_IMAGE="${OPERATOR_RUNNER_IMAGE:-$(pinned_image)}" OPERATOR_HOST="$(host_name)" \
    OPERATOR_RUNNER_GROUP="${RUNNER_GROUP:-$GROUP_DEFAULT}" \
    docker compose -f "$COMPOSE" "$@"
}

cmd_image() {
  check_prerequisites
  if [[ "${1:-}" == --build ]]; then
    info "building $LOCAL_TAG for linux/amd64 from apps/containers/ci-runner"
    bash "$REPO_ROOT/scripts/ci-runner-image.sh" --load --tag "$LOCAL_TAG"
    echo "export OPERATOR_RUNNER_IMAGE=$LOCAL_TAG   # use this for register/start"
    return
  fi
  local image
  image="$(pinned_image)"
  info "pulling $image (private ghcr.io; needs docker login with a read:packages token)"
  if ! docker pull --platform linux/amd64 "$image"; then
    cat >&2 <<EOF
pull failed. Either grant the CLI token read:packages and log in:
  gh auth refresh -h github.com -s read:packages
  gh auth token | docker login ghcr.io -u "\$(gh api user --jq .login)" --password-stdin
or build the same Dockerfile locally: $0 image --build
EOF
    exit 1
  fi
}

require_token() {
  [[ -n "${RUNNER_TOKEN:-}" ]] || die 'RUNNER_TOKEN is required; see: token-help'
}

cmd_register() {
  check_prerequisites
  require_token
  local service
  for service in $(services); do
    info "registering $service as mac-operator-$(host_name)-${service#runner-} in group ${RUNNER_GROUP:-$GROUP_DEFAULT}"
    # The token is passed only to this one-off container, which exits after
    # storing credentials; it never lands in the persistent container config.
    compose run --rm --no-deps -e RUNNER_TOKEN "$service" register
  done
  info 'registered; containers are stopped. Start the window with: start'
}

cmd_start() {
  check_prerequisites
  # shellcheck disable=SC2046
  compose up -d $(services)
  info 'runners started; verify with: status'
}

cmd_stop() {
  check_prerequisites
  compose stop
  info 'runners stopped'
}

cmd_status() {
  check_prerequisites
  compose ps
  local prefix
  prefix="mac-operator-$(host_name)-"
  gh api --paginate "orgs/${ORG}/actions/runners" --jq \
    ".runners[] | select(.name | startswith(\"$prefix\")) | \"\\(.name) status=\\(.status) busy=\\(.busy) labels=\\([.labels[].name] | join(\",\"))\"" 2>/dev/null \
    || gh api --paginate "repos/${REPO}/actions/runners" --jq \
    ".runners[] | select(.name | startswith(\"$prefix\")) | \"\\(.name) status=\\(.status) busy=\\(.busy)\""
}

cmd_remove() {
  check_prerequisites
  require_token
  compose stop
  local service
  for service in $(services); do
    info "deregistering $service"
    compose run --rm --no-deps -e RUNNER_TOKEN "$service" remove || true
  done
  compose down --volumes
  info 'removed runners, containers and volumes'
}

cmd_token_help() {
  cat <<EOF
Registration token (60 minutes, org level so the runner joins the runner group):
  RUNNER_TOKEN="\$(gh api -X POST orgs/${ORG}/actions/runners/registration-token --jq .token)" $0 register
Removal token:
  RUNNER_TOKEN="\$(gh api -X POST orgs/${ORG}/actions/runners/remove-token --jq .token)" $0 remove
Both need a gh token with admin:org (gh auth refresh -h github.com -s admin:org).
Set RUNNERS=1..3 to register or start fewer than three runners.
EOF
}

main() {
  case "${1:-}" in
    image) shift; cmd_image "$@" ;;
    register) cmd_register ;;
    start) cmd_start ;;
    stop) cmd_stop ;;
    status) cmd_status ;;
    remove) cmd_remove ;;
    token-help) cmd_token_help ;;
    *) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
  esac
}

main "$@"
