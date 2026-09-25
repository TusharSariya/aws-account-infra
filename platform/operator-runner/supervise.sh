#!/bin/bash
# One supervisor loop = one ephemeral operator runner slot on the owner's Mac.
#
# Each iteration mints a single-use just-in-time runner configuration for the
# restricted org runner group, starts a fresh container from the pinned ARC
# runner image, runs exactly one job, and discards the container. Nothing from
# the host is mounted and no credentials are stored: the JIT configuration is
# only ever passed as an environment variable to that one container, and GitHub
# deletes the runner record when the job ends.
#
# Started and stopped only by scripts/mac-operator-containers.sh, which passes:
#   OPERATOR_SLOT            1..N (part of the runner name)
#   OPERATOR_RUNNER_IMAGE    image reference (ARC digest or a local build)
#   OPERATOR_GROUP_ID        numeric org runner group id
#   OPERATOR_HOST            lower-case LocalHostName
#   OPERATOR_RUN_FLAG        the loop exits once this file disappears
# Compatible with macOS /bin/bash 3.2.
set -euo pipefail

: "${OPERATOR_SLOT:?}" "${OPERATOR_RUNNER_IMAGE:?}" "${OPERATOR_GROUP_ID:?}" "${OPERATOR_HOST:?}" "${OPERATOR_RUN_FLAG:?}"
readonly ORG=TusharSariyaOrg
readonly LABEL=homelab-operator
readonly CONTAINER="homelab-operator-${OPERATOR_SLOT}"

log() {
  printf '%s slot=%s %s\n' "$(date -u +%FT%TZ)" "$OPERATOR_SLOT" "$*"
}

while [[ -f "$OPERATOR_RUN_FLAG" ]]; do
  name="mac-operator-${OPERATOR_HOST}-${OPERATOR_SLOT}-$(date -u +%Y%m%dT%H%M%SZ)"
  # Single-use configuration: consumed by the runner below, invalid afterwards.
  if ! ACTIONS_RUNNER_INPUT_JITCONFIG="$(gh api -X POST "orgs/${ORG}/actions/runners/generate-jitconfig" \
      -f "name=${name}" -F "runner_group_id=${OPERATOR_GROUP_ID}" -f "labels[]=${LABEL}" \
      -f work_folder=_work --jq .encoded_jit_config)"; then
    log 'could not mint a JIT runner configuration; retrying in 60s'
    sleep 60
    continue
  fi
  export ACTIONS_RUNNER_INPUT_JITCONFIG
  log "starting ${name}"
  # Fresh container per job. Only NET_ADMIN and a TUN device for the job's own
  # Tailscale node; no host mounts, no Docker socket, no privileged mode.
  docker run --rm --name "$CONTAINER" --platform linux/amd64 --init \
    --cap-add NET_ADMIN --device /dev/net/tun:/dev/net/tun \
    --cpus 4 --memory 4g \
    -e ACTIONS_RUNNER_INPUT_JITCONFIG \
    "$OPERATOR_RUNNER_IMAGE" /home/runner/run.sh || log "runner exited with status $?"
  unset ACTIONS_RUNNER_INPUT_JITCONFIG
  log "finished ${name}"
  # Brief pause so a broken image cannot spin the loop and mint configs nonstop.
  sleep 5
done
log 'run flag removed; supervisor exiting'
