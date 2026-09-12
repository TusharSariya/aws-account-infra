#!/usr/bin/env bash

# Fetch and verify a sanitized Proxmox baseline archive on macOS or Linux.
# Usage: ./proxmox-baseline-fetch.sh <ssh-target> <remote-archive> [destination]

set -euo pipefail

readonly SCRIPT_NAME="${0##*/}"

usage() {
  printf 'Usage: %s <ssh-target> <remote-archive> [destination]\n' \
    "$SCRIPT_NAME" >&2
  printf 'Example: %s root@192.0.2.10 /root/pve-empty-host-baseline-20260825T220000Z.tar.gz\n' \
    "$SCRIPT_NAME" >&2
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

if (( $# < 2 || $# > 3 )); then
  usage
  exit 2
fi

readonly SSH_TARGET="$1"
readonly REMOTE_ARCHIVE="$2"
readonly DESTINATION_DIRECTORY="${3:-${HOME}/Backups/proxmox/pve}"

[[ "$SSH_TARGET" =~ ^[A-Za-z0-9._@:-]+$ ]] \
  || fail "SSH target contains unsupported characters"

[[ "$REMOTE_ARCHIVE" =~ ^/root/pve-empty-host-baseline-[0-9]{8}T[0-9]{6}Z\.tar\.gz$ ]] \
  || fail "remote archive does not match the expected /root baseline path"

readonly ARCHIVE_FILENAME="${REMOTE_ARCHIVE##*/}"
readonly LOCAL_ARCHIVE="${DESTINATION_DIRECTORY%/}/${ARCHIVE_FILENAME}"
readonly LOCAL_CHECKSUM="${LOCAL_ARCHIVE}.sha256"

for required_command in awk grep scp shasum tar; do
  command -v "$required_command" >/dev/null 2>&1 \
    || fail "required command is unavailable: $required_command"
done

install -d -m 0700 "$DESTINATION_DIRECTORY"

[[ ! -e "$LOCAL_ARCHIVE" ]] || fail "local archive already exists: $LOCAL_ARCHIVE"
[[ ! -e "$LOCAL_CHECKSUM" ]] || fail "local checksum already exists: $LOCAL_CHECKSUM"

scp -- \
  "${SSH_TARGET}:${REMOTE_ARCHIVE}" \
  "${SSH_TARGET}:${REMOTE_ARCHIVE}.sha256" \
  "$DESTINATION_DIRECTORY/"

EXPECTED_SHA256="$(awk 'NR == 1 { print $1 }' "$LOCAL_CHECKSUM")"
readonly EXPECTED_SHA256
ACTUAL_SHA256="$(shasum -a 256 "$LOCAL_ARCHIVE" | awk '{ print $1 }')"
readonly ACTUAL_SHA256

[[ "$EXPECTED_SHA256" =~ ^[0-9a-f]{64}$ ]] \
  || fail "remote checksum file does not contain a valid SHA-256 value"
[[ "$ACTUAL_SHA256" == "$EXPECTED_SHA256" ]] \
  || fail "checksum mismatch: expected $EXPECTED_SHA256, got $ACTUAL_SHA256"

ARCHIVE_LISTING="$(mktemp "${TMPDIR:-/tmp}/proxmox-baseline-listing.XXXXXX")"
readonly ARCHIVE_LISTING

cleanup() {
  if [[ -f "$ARCHIVE_LISTING" ]]; then
    rm -- "$ARCHIVE_LISTING"
  fi
}

trap cleanup EXIT

tar -tzf "$LOCAL_ARCHIVE" >"$ARCHIVE_LISTING"

readonly REQUIRED_ARCHIVE_PATHS=(
  ./config/etc/network/interfaces
  ./config/etc/pve/storage.cfg
  ./inventory/pve-version.txt
  ./inventory/storage-status.txt
)

for required_path in "${REQUIRED_ARCHIVE_PATHS[@]}"; do
  grep -Fxq "$required_path" "$ARCHIVE_LISTING" \
    || fail "required archive entry is missing: $required_path"
done

printf 'BASELINE_FILE=%s\n' "$LOCAL_ARCHIVE"
printf 'BASELINE_SHA256=%s\n' "$ACTUAL_SHA256"
printf 'BASELINE_LISTING_VERIFIED=yes\n'
printf 'VERIFIED_PATHS:\n'
printf '  %s\n' "${REQUIRED_ARCHIVE_PATHS[@]}"
