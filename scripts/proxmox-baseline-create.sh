#!/usr/bin/env bash

# Create a sanitized baseline archive for a new, empty Proxmox host.
# Usage: ./proxmox-baseline-create.sh [output-directory]

set -euo pipefail

readonly SCRIPT_NAME="${0##*/}"
readonly OUTPUT_DIRECTORY="${1:-/root}"

usage() {
  printf 'Usage: %s [output-directory]\n' "$SCRIPT_NAME" >&2
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

if (( $# > 1 )); then
  usage
  exit 2
fi

if (( EUID != 0 )); then
  fail "run this script as root on the Proxmox host"
fi

case "$OUTPUT_DIRECTORY" in
  /*) ;;
  *) fail "output directory must be an absolute path" ;;
esac

[[ -d "$OUTPUT_DIRECTORY" ]] || fail "output directory does not exist: $OUTPUT_DIRECTORY"
[[ -w "$OUTPUT_DIRECTORY" ]] || fail "output directory is not writable: $OUTPUT_DIRECTORY"

readonly REQUIRED_COMMANDS=(
  cp
  dpkg-query
  find
  grep
  ip
  lscpu
  lsblk
  lvs
  pct
  pvesm
  pveversion
  pvs
  qm
  sha256sum
  tar
  vgs
)

for required_command in "${REQUIRED_COMMANDS[@]}"; do
  command -v "$required_command" >/dev/null 2>&1 \
    || fail "required command is unavailable: $required_command"
done

BASELINE_TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly BASELINE_TIMESTAMP
readonly BASELINE_FILENAME="pve-empty-host-baseline-${BASELINE_TIMESTAMP}.tar.gz"
readonly BASELINE_ARCHIVE="${OUTPUT_DIRECTORY%/}/${BASELINE_FILENAME}"
readonly BASELINE_CHECKSUM="${BASELINE_ARCHIVE}.sha256"
BASELINE_STAGE="$(mktemp -d /run/proxmox-baseline.XXXXXX)"
readonly BASELINE_STAGE

cleanup() {
  case "$BASELINE_STAGE" in
    /run/proxmox-baseline.*)
      if [[ -d "$BASELINE_STAGE" ]]; then
        find "$BASELINE_STAGE" -mindepth 1 -delete
        rmdir "$BASELINE_STAGE"
      fi
      ;;
    *)
      printf 'WARNING: refusing to clean unexpected staging path: %s\n' \
        "$BASELINE_STAGE" >&2
      ;;
  esac
}

trap cleanup EXIT

[[ ! -e "$BASELINE_ARCHIVE" ]] || fail "archive already exists: $BASELINE_ARCHIVE"
[[ ! -e "$BASELINE_CHECKSUM" ]] || fail "checksum already exists: $BASELINE_CHECKSUM"

install -d -m 0700 \
  "$BASELINE_STAGE/config" \
  "$BASELINE_STAGE/inventory"

readonly CONFIGURATION_PATHS=(
  /etc/network/interfaces
  /etc/sysctl.d/99-homelab-tailscale.conf
  /etc/network/interfaces.d
  /etc/hosts
  /etc/hostname
  /etc/resolv.conf
  /etc/apt/sources.list
  /etc/apt/sources.list.d
  /etc/pve/storage.cfg
  /etc/pve/datacenter.cfg
  /etc/pve/firewall
  /etc/default/grub
  /etc/kernel/cmdline
  /etc/kernel/proxmox-boot-uuids
  /etc/modules
  /etc/modules-load.d
  /etc/modprobe.d
)

for configuration_path in "${CONFIGURATION_PATHS[@]}"; do
  if [[ -e "$configuration_path" ]]; then
    cp -a --parents "$configuration_path" "$BASELINE_STAGE/config"
  fi
done

pveversion -v >"$BASELINE_STAGE/inventory/pve-version.txt"
pvesm status >"$BASELINE_STAGE/inventory/storage-status.txt"
pvesm list local >"$BASELINE_STAGE/inventory/local-storage-inventory.txt"
qm list >"$BASELINE_STAGE/inventory/vm-list.txt"
pct list >"$BASELINE_STAGE/inventory/container-list.txt"
ip -brief address >"$BASELINE_STAGE/inventory/ip-addresses.txt"
ip route show table all >"$BASELINE_STAGE/inventory/ip-routes.txt"
lsblk -o NAME,TYPE,SIZE,FSTYPE,UUID,MOUNTPOINTS \
  >"$BASELINE_STAGE/inventory/block-devices.txt"
pvs --units g >"$BASELINE_STAGE/inventory/lvm-pvs.txt"
vgs --units g >"$BASELINE_STAGE/inventory/lvm-vgs.txt"
lvs --units g -a >"$BASELINE_STAGE/inventory/lvm-lvs.txt"
lscpu >"$BASELINE_STAGE/inventory/cpu.txt"
dpkg-query -W -f='${binary:Package}\t${Version}\n' \
  >"$BASELINE_STAGE/inventory/packages.txt"

printf '%s\n' \
  'Sanitized baseline for a new, empty Proxmox host.' \
  'Intentionally excluded: /etc/pve/priv, /etc/pve/user.cfg, /etc/shadow,' \
  '/etc/ssh, and /var/lib/pve-cluster/config.db.' \
  >"$BASELINE_STAGE/README.txt"

readonly SECRET_PATTERN='(password|passwd|api[-_]?token|private[-_]?key|secret|https?://[^/[:space:]]+:[^/@[:space:]]+@)'
mapfile -t SUSPECT_FILES < <(
  grep -RIlE "$SECRET_PATTERN" "$BASELINE_STAGE/config" 2>/dev/null || true
)
readonly SUSPECT_FILES

if (( ${#SUSPECT_FILES[@]} > 0 )); then
  printf 'Potential secret-bearing files detected; no archive was created:\n' >&2
  printf '  %s\n' "${SUSPECT_FILES[@]}" >&2
  fail "review only the listed filenames; do not print their contents"
fi

tar \
  --acls \
  --xattrs \
  --numeric-owner \
  -C "$BASELINE_STAGE" \
  -czf "$BASELINE_ARCHIVE" \
  .

chmod 0600 "$BASELINE_ARCHIVE"
tar -tzf "$BASELINE_ARCHIVE" >/dev/null

(
  cd "$OUTPUT_DIRECTORY"
  sha256sum "$BASELINE_FILENAME" >"${BASELINE_FILENAME}.sha256"
)
chmod 0600 "$BASELINE_CHECKSUM"

printf 'BASELINE_FILE=%s\n' "$BASELINE_ARCHIVE"
printf 'BASELINE_CHECKSUM_FILE=%s\n' "$BASELINE_CHECKSUM"
printf 'BASELINE_SHA256='
cut -d ' ' -f 1 "$BASELINE_CHECKSUM"
printf 'SECRET_SCAN=passed\n'
