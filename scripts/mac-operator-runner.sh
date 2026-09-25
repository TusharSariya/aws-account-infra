#!/usr/bin/env bash
# Bootstrap and operate the macOS "homelab-operator" GitHub Actions runner that
# executes cluster-mutating maintenance (see docs/runbooks/mac-operator-runner.md).
#
#   install     create the non-admin runner user, verify and unpack the runner,
#               register it (RUNNER_TOKEN from the environment) and install the
#               LaunchDaemon. The runner is left stopped.
#   start       load and start the LaunchDaemon (maintenance window opens)
#   stop        stop and unload the LaunchDaemon (maintenance window closes)
#   status      launchd state plus the runner's GitHub online/busy status
#   uninstall   stop, deregister (RUNNER_TOKEN must be a removal token), delete plist
#   token-help  print how to obtain registration and removal tokens
#
# Compatible with macOS /bin/bash 3.2. Never prints RUNNER_TOKEN.
set -euo pipefail

readonly RUNNER_VERSION=2.337.0
readonly RUNNER_ASSET="actions-runner-osx-arm64-${RUNNER_VERSION}.tar.gz"
readonly RUNNER_SHA256=5a2cd92908a93d7276a194e1de6008099f3e7946f3f8e14aa7a1a7b4a31fdec2
readonly RUNNER_DOWNLOAD="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${RUNNER_ASSET}"
readonly REPO=TusharSariyaOrg/aws-account-infra
readonly REPO_URL="https://github.com/${REPO}"
readonly RUNNER_LABELS=homelab-operator
readonly LABEL=dev.tfdraw.homelab.operator-runner
readonly PLIST="/Library/LaunchDaemons/${LABEL}.plist"
readonly RUNNER_PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
readonly DEFAULT_USER=ghrunner
readonly DEFAULT_HOME=/Users/ghrunner

RUNNER_USER="${RUNNER_USER:-$DEFAULT_USER}"
RUNNER_HOME="${RUNNER_HOME:-/Users/$RUNNER_USER}"
INSTALL_DIR="$RUNNER_HOME/actions-runner"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$REPO_ROOT/platform/operator-runner/${LABEL}.plist"

# Homebrew formulae the operator jobs need; the script checks but never installs them.
readonly BREW_FORMULAE='opentofu uv helm kubernetes-cli jq gh tailscale python@3.13 awscli'
readonly REQUIRED_COMMANDS='tofu uv helm kubectl jq gh tailscale python3.13 aws git curl unzip'

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

info() {
  printf '==> %s\n' "$*"
}

runner_name() {
  printf 'mac-operator-%s' "$(scutil --get LocalHostName)"
}

require_macos_arm64() {
  [[ "$(uname -s)" == Darwin ]] || die 'the operator runner is macOS only'
  [[ "$(uname -m)" == arm64 ]] || die "runner asset ${RUNNER_ASSET} requires Apple silicon (arm64)"
}

require_admin() {
  if ! sudo -n true 2>/dev/null; then
    info 'administrator privileges are required; sudo will prompt'
    sudo -v || die 'run this from an administrator account'
  fi
}

require_token() {
  local purpose="$1"
  if [[ -z "${RUNNER_TOKEN:-}" ]]; then
    die "RUNNER_TOKEN must hold a ${purpose} token; run '$0 token-help'"
  fi
}

require_name_prefix() {
  local name
  name="$(runner_name)"
  # setup-opentofu and talos-runner-setup treat homelab-talos-* as ARC pods.
  case "$name" in
    homelab-talos-*) die "runner name ${name} must not start with homelab-talos-" ;;
  esac
}

check_prerequisites() {
  local missing='' tool
  for tool in $REQUIRED_COMMANDS; do
    PATH="$RUNNER_PATH" command -v "$tool" >/dev/null 2>&1 || missing="$missing $tool"
  done
  if [[ -n "$missing" ]]; then
    printf 'missing on the runner PATH (%s):%s\n' "$RUNNER_PATH" "$missing" >&2
    printf 'install with: brew install %s\n' "$BREW_FORMULAE" >&2
    printf 'tailscale: the Mac must already be on the tailnet with accepted routes and MagicDNS\n' >&2
    return 1
  fi
  PATH="$RUNNER_PATH" python3 -c 'import sys; assert sys.version_info >= (3, 11)' 2>/dev/null ||
    die "python3 on ${RUNNER_PATH} is older than 3.11; link Homebrew python@3.13 (brew link python@3.13)"
  info 'Homebrew prerequisites present'
}

ensure_user() {
  if id -u "$RUNNER_USER" >/dev/null 2>&1; then
    info "user ${RUNNER_USER} already exists"
  else
    info "creating standard (non-admin) user ${RUNNER_USER}"
    info 'sysadminctl prompts for a password: enter a long random value and do not record it'
    sudo sysadminctl -addUser "$RUNNER_USER" -fullName 'GitHub operator runner' \
      -home "$RUNNER_HOME" -password -
  fi
  # No interactive login: the LaunchDaemon starts the runner via UserName.
  sudo dscl . -create "/Users/$RUNNER_USER" UserShell /usr/bin/false
  sudo dscl . -create "/Users/$RUNNER_USER" IsHidden 1
  if dseditgroup -o checkmember -m "$RUNNER_USER" admin >/dev/null 2>&1; then
    die "${RUNNER_USER} is an administrator; the runner user must be a standard account"
  fi
  if [[ ! -d "$RUNNER_HOME" ]]; then
    sudo createhomedir -c -u "$RUNNER_USER" >/dev/null
  fi
  sudo chown "$RUNNER_USER:staff" "$RUNNER_HOME"
  sudo chmod 700 "$RUNNER_HOME"
}

as_runner() {
  # Run from the install directory; the invoking admin's cwd may be unreadable.
  sudo -u "$RUNNER_USER" -H /bin/bash -c 'cd "$1" && shift && exec "$@"' _ "$INSTALL_DIR" "$@"
}

unpack_runner() {
  local work archive actual
  if [[ -f "$INSTALL_DIR/.runner" ]]; then
    info "runner already configured in ${INSTALL_DIR}; re-registering with --replace"
  fi
  work="$(mktemp -d)"
  # shellcheck disable=SC2064  # expand now: the trap must remove this exact directory
  trap "rm -rf '$work'" EXIT
  archive="$work/$RUNNER_ASSET"
  info "downloading ${RUNNER_ASSET}"
  curl -fsSL --retry 3 -o "$archive" "$RUNNER_DOWNLOAD"
  actual="$(shasum -a 256 "$archive" | awk '{print $1}')"
  [[ "$actual" == "$RUNNER_SHA256" ]] || die "checksum mismatch for ${RUNNER_ASSET}: ${actual}"
  info 'checksum verified'
  sudo install -d -o "$RUNNER_USER" -g staff -m 700 "$INSTALL_DIR"
  sudo tar -xzf "$archive" -C "$INSTALL_DIR"
  sudo chown -R "$RUNNER_USER:staff" "$INSTALL_DIR"
  sudo install -d -o "$RUNNER_USER" -g staff -m 700 "$INSTALL_DIR/_diag"
  rm -rf "$work"
  trap - EXIT
}

configure_runner() {
  local name
  name="$(runner_name)"
  info "registering ${name} with ${REPO_URL} (labels: ${RUNNER_LABELS})"
  if [[ -n "${RUNNER_GROUP:-}" ]]; then
    as_runner ./config.sh --unattended --url "$REPO_URL" --token "$RUNNER_TOKEN" \
      --name "$name" --labels "$RUNNER_LABELS" --work _work --replace \
      --runnergroup "$RUNNER_GROUP"
  else
    as_runner ./config.sh --unattended --url "$REPO_URL" --token "$RUNNER_TOKEN" \
      --name "$name" --labels "$RUNNER_LABELS" --work _work --replace
  fi
  # The runner exports .path as PATH for every job step.
  # shellcheck disable=SC2016  # $1 is expanded by the inner shell
  as_runner /bin/sh -c 'printf "%s\n" "$1" > .path' _ "$RUNNER_PATH"
}

install_plist() {
  local rendered
  [[ -f "$TEMPLATE" ]] || die "missing template ${TEMPLATE}"
  rendered="$(mktemp)"
  sed -e "s|${DEFAULT_HOME}|${RUNNER_HOME}|g" \
    -e "s|<string>${DEFAULT_USER}</string>|<string>${RUNNER_USER}</string>|" \
    "$TEMPLATE" >"$rendered"
  plutil -lint "$rendered" >/dev/null
  sudo install -o root -g wheel -m 644 "$rendered" "$PLIST"
  rm -f "$rendered"
  info "installed ${PLIST} (RunAtLoad false, KeepAlive false)"
}

loaded() {
  sudo launchctl print "system/${LABEL}" >/dev/null 2>&1
}

cmd_install() {
  require_macos_arm64
  require_name_prefix
  require_token registration
  check_prerequisites
  require_admin
  ensure_user
  unpack_runner
  configure_runner
  install_plist
  if loaded; then
    sudo launchctl bootout "system/${LABEL}" || true
  fi
  info "installed and stopped. Open a maintenance window with: $0 start"
}

cmd_start() {
  require_admin
  [[ -f "$PLIST" ]] || die "not installed; run $0 install"
  if ! loaded; then
    sudo launchctl bootstrap system "$PLIST"
  fi
  sudo launchctl kickstart "system/${LABEL}"
  info "runner started; stop it after maintenance with: $0 stop"
}

cmd_stop() {
  require_admin
  if loaded; then
    sudo launchctl bootout "system/${LABEL}"
    info 'runner stopped'
  else
    info 'runner is not loaded'
  fi
}

cmd_status() {
  local name github
  name="$(runner_name)"
  if [[ -f "$PLIST" ]]; then
    info "launchd: ${PLIST}"
    if launchctl print "system/${LABEL}" 2>/dev/null |
      grep -E '^[[:space:]]*(state|pid|last exit code|runs) = '; then
      :
    else
      printf '    not loaded (stopped)\n'
    fi
  else
    info 'launchd: not installed'
  fi
  info "GitHub: ${name}"
  if command -v gh >/dev/null 2>&1; then
    if github="$(gh api "repos/${REPO}/actions/runners" --paginate \
      --jq ".runners[] | select(.name == \"${name}\") | \"    status=\\(.status) busy=\\(.busy) labels=\\([.labels[].name] | join(\",\"))\"")"; then
      printf '%s\n' "${github:-    not registered}"
    else
      printf '    could not query runners (needs repository admin access)\n'
    fi
  else
    printf '    gh not installed\n'
  fi
  check_prerequisites || true
}

cmd_uninstall() {
  require_token removal
  require_admin
  cmd_stop
  if [[ -f "$INSTALL_DIR/.runner" ]]; then
    as_runner ./config.sh remove --token "$RUNNER_TOKEN"
  else
    info 'runner is not registered locally'
  fi
  if [[ -f "$PLIST" ]]; then
    sudo rm -f "$PLIST"
    info "removed ${PLIST}"
  fi
  info "kept ${INSTALL_DIR} and user ${RUNNER_USER}; remove them with: sudo sysadminctl -deleteUser ${RUNNER_USER}"
}

cmd_token_help() {
  cat <<EOF
RUNNER_TOKEN is read from the environment and never printed. Tokens expire 60 minutes
after they are issued and need repository admin access.

Registration token (install):
  RUNNER_TOKEN="\$(gh api -X POST repos/${REPO}/actions/runners/registration-token --jq .token)" $0 install
  or: ${REPO_URL}/settings/actions/runners > New self-hosted runner (macOS, ARM64),
      and copy the value after --token.

Removal token (uninstall):
  RUNNER_TOKEN="\$(gh api -X POST repos/${REPO}/actions/runners/remove-token --jq .token)" $0 uninstall

Optional: RUNNER_GROUP=homelab-operator registers into the org runner group (create it first;
see docs/runbooks/mac-operator-runner.md).
EOF
}

main() {
  local command="${1:-}"
  case "$command" in
    install) cmd_install ;;
    start) cmd_start ;;
    stop) cmd_stop ;;
    status) cmd_status ;;
    uninstall) cmd_uninstall ;;
    token-help) cmd_token_help ;;
    *)
      printf 'usage: %s {install|start|stop|status|uninstall|token-help}\n' "$0" >&2
      exit 2
      ;;
  esac
}

main "$@"
