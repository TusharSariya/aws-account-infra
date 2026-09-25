#!/bin/bash
# Entrypoint for one persistent operator runner container (compose.yaml).
#
#   register   configure the runner once; RUNNER_TOKEN is read from
#              /run/secrets/runner_token or the environment and never echoed.
#              Credentials are copied into the state volume, then the process exits.
#   run        (default) restore credentials from the state volume and run jobs.
#   remove     deregister using a removal token, then clear the state volume.
set -euo pipefail
STATE=/home/runner/state
WORK=/home/runner/_work
# Named volumes are created root-owned. The container starts as root only to hand
# the two volumes to the runner user, then re-executes itself unprivileged.
if [[ "$(id -u)" == 0 ]]; then
  mkdir -p "$STATE" "$WORK"
  chown runner:runner "$STATE" "$WORK"
  chmod 700 "$STATE"
  exec runuser -u runner -- "$0" "$@"
fi
[[ "$(id -un)" == runner ]] || { echo 'entrypoint must run as the runner user' >&2; exit 1; }
cd /home/runner
CREDENTIALS=".runner .credentials .credentials_rsaparams"
NAME="${RUNNER_NAME_PREFIX:?}-${RUNNER_INDEX:?}"

token() {
  if [[ -r /run/secrets/runner_token ]]; then
    cat /run/secrets/runner_token
  elif [[ -n "${RUNNER_TOKEN:-}" ]]; then
    printf '%s' "$RUNNER_TOKEN"
  else
    echo 'RUNNER_TOKEN is required (registration or removal token)' >&2
    exit 1
  fi
}

case "${1:-run}" in
  register)
    # Environment variables inherited into every job and its steps live in
    # .env, so the operator origin is visible to workflows if ever needed.
    printf 'HOMELAB_OPERATOR_CONTAINER=1\n' > .env
    ./config.sh --unattended --replace --disableupdate \
      --url "${RUNNER_URL:?}" --token "$(token)" \
      --runnergroup "${RUNNER_GROUP:?}" --labels "${RUNNER_LABELS:?}" \
      --name "$NAME" --work _work
    for file in $CREDENTIALS .env; do
      install -m 600 "$file" "$STATE/$file"
    done
    echo "registered $NAME; credentials stored in the state volume"
    ;;
  run)
    for file in $CREDENTIALS; do
      if [[ ! -f "$STATE/$file" ]]; then
        echo "no stored credentials for $NAME; run: scripts/mac-operator-containers.sh register" >&2
        exit 1
      fi
      install -m 600 "$STATE/$file" "$file"
    done
    if [[ -f "$STATE/.env" ]]; then install -m 600 "$STATE/.env" .env; fi
    unset RUNNER_TOKEN
    exec ./run.sh
    ;;
  remove)
    for file in $CREDENTIALS; do
      if [[ -f "$STATE/$file" ]]; then install -m 600 "$STATE/$file" "$file"; fi
    done
    ./config.sh remove --token "$(token)"
    rm -f "$STATE"/.runner "$STATE"/.credentials "$STATE"/.credentials_rsaparams "$STATE"/.env
    echo "removed $NAME"
    ;;
  *)
    echo "usage: entrypoint.sh {register|run|remove}" >&2
    exit 2
    ;;
esac
