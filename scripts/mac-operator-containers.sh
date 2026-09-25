#!/usr/bin/env bash
# Operate the parallel "homelab-operator" GitHub Actions runners that run as
# ephemeral Linux containers on the owner's Mac (platform/operator-runner/supervise.sh
# and docs/runbooks/mac-operator-runner.md).
#
#   image        pull the ARC runner image at the digest pinned in
#                config/environments/kubernetes/homelab-ci/arc-runner-values.yaml
#                (--build builds it locally from apps/containers/ci-runner instead)
#   start        start RUNNERS (default 3) supervisor loops; each runs one job per
#                fresh container using a single-use JIT configuration
#   stop         stop minting new runners, wait for running jobs to finish
#                (--now stops the containers immediately)
#   status       supervisors, containers, and GitHub online/busy per runner
#   cleanup      delete stale offline mac-operator-* runner records from GitHub
#
# Needs a gh login with admin:org (JIT configs) and OrbStack or Docker Desktop.
# Compatible with macOS /bin/bash 3.2. Never prints a JIT configuration.
set -euo pipefail

readonly ORG=TusharSariyaOrg
readonly GROUP=homelab-operator
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
readonly SUPERVISOR="$REPO_ROOT/platform/operator-runner/supervise.sh"
readonly VALUES="$REPO_ROOT/config/environments/kubernetes/homelab-ci/arc-runner-values.yaml"
readonly LOCAL_TAG=homelab-ci-runner:operator-local
readonly STATE="${OPERATOR_STATE_DIR:-$HOME/.local/state/homelab-operator}"
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

group_id() {
  gh api "orgs/${ORG}/actions/runner-groups" --jq ".runner_groups[] | select(.name == \"${GROUP}\") | .id"
}

check_prerequisites() {
  [[ "$(uname -s)" == Darwin ]] || die 'the container operator runners are designed for the owner Mac'
  command -v docker > /dev/null || die 'docker CLI missing (OrbStack or Docker Desktop)'
  docker info > /dev/null 2>&1 || die 'docker engine not running (start OrbStack)'
  command -v gh > /dev/null || die 'gh missing (brew install gh)'
  command -v python3 > /dev/null || die 'python3 missing'
  [[ "$RUNNERS" =~ ^[1-9]$ ]] || die 'RUNNERS must be 1..9'
  mkdir -p "$STATE"
  chmod 700 "$STATE"
}

cmd_image() {
  check_prerequisites
  if [[ "${1:-}" == --build ]]; then
    info "building $LOCAL_TAG for linux/amd64 from apps/containers/ci-runner"
    bash "$REPO_ROOT/scripts/ci-runner-image.sh" --load --tag "$LOCAL_TAG"
    echo "export OPERATOR_RUNNER_IMAGE=$LOCAL_TAG   # use this for start"
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

supervisor_alive() {
  local pid_file="$STATE/supervisor-$1.pid"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2> /dev/null
}

cmd_start() {
  check_prerequisites
  local image gid host slot
  image="${OPERATOR_RUNNER_IMAGE:-$(pinned_image)}"
  docker image inspect "$image" > /dev/null 2>&1 || die "image $image is not present; run: $0 image"
  gid="$(group_id)"
  [[ "$gid" =~ ^[0-9]+$ ]] || die "runner group ${GROUP} not found (needs admin:org)"
  host="$(host_name)"
  slot=1
  while (( slot <= RUNNERS )); do
    if supervisor_alive "$slot"; then
      info "slot $slot already running"
    else
      : > "$STATE/run-$slot.flag"
      OPERATOR_SLOT="$slot" OPERATOR_RUNNER_IMAGE="$image" OPERATOR_GROUP_ID="$gid" OPERATOR_HOST="$host" \
        OPERATOR_RUN_FLAG="$STATE/run-$slot.flag" \
        nohup bash "$SUPERVISOR" >> "$STATE/supervisor-$slot.log" 2>&1 &
      echo $! > "$STATE/supervisor-$slot.pid"
      info "slot $slot started (log: $STATE/supervisor-$slot.log)"
    fi
    slot=$((slot + 1))
  done
  info 'maintenance window open; verify with: status'
}

cmd_stop() {
  check_prerequisites
  local flag
  for flag in "$STATE"/run-*.flag; do
    [[ -e "$flag" ]] && rm -f "$flag"
  done
  if [[ "${1:-}" == --now ]]; then
    local running
    running="$(docker ps -q --filter name='^homelab-operator-')"
    # shellcheck disable=SC2086
    [[ -z "$running" ]] || docker stop $running > /dev/null
    info 'containers stopped'
  else
    info 'no new runners will be minted; waiting for running jobs to finish'
    while [[ -n "$(docker ps -q --filter name='^homelab-operator-')" ]]; do sleep 10; done
  fi
  local pid_file
  for pid_file in "$STATE"/supervisor-*.pid; do
    [[ -e "$pid_file" ]] || continue
    kill "$(cat "$pid_file")" 2> /dev/null || true
    rm -f "$pid_file"
  done
  info 'maintenance window closed'
}

cmd_status() {
  check_prerequisites
  local pid_file slot
  for pid_file in "$STATE"/supervisor-*.pid; do
    [[ -e "$pid_file" ]] || continue
    slot="${pid_file##*/supervisor-}"; slot="${slot%.pid}"
    if supervisor_alive "$slot"; then echo "supervisor $slot running"; else echo "supervisor $slot dead"; fi
  done
  docker ps --filter name='^homelab-operator-' --format 'container {{.Names}} {{.Status}}'
  gh api --paginate "orgs/${ORG}/actions/runners" --jq \
    ".runners[] | select(.name | startswith(\"mac-operator-$(host_name)-\")) | \"\\(.name) status=\\(.status) busy=\\(.busy) labels=\\([.labels[].name] | join(\",\"))\""
}

cmd_cleanup() {
  check_prerequisites
  local id
  for id in $(gh api --paginate "orgs/${ORG}/actions/runners" --jq \
      ".runners[] | select((.name | startswith(\"mac-operator-$(host_name)-\")) and .status == \"offline\" and .busy == false) | .id"); do
    gh api -X DELETE "orgs/${ORG}/actions/runners/${id}" > /dev/null && info "deleted stale runner ${id}"
  done
}

main() {
  case "${1:-}" in
    image) shift; cmd_image "$@" ;;
    start) cmd_start ;;
    stop) shift; cmd_stop "$@" ;;
    status) cmd_status ;;
    cleanup) cmd_cleanup ;;
    *) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
  esac
}

main "$@"
