#!/usr/bin/env bash
set -euo pipefail

readonly MODE="${1:-}"
readonly SOURCES_DIR="/etc/apt/sources.list.d"
readonly PVE_ENTERPRISE_SOURCE="${SOURCES_DIR}/pve-enterprise.sources"
readonly CEPH_ENTERPRISE_SOURCE="${SOURCES_DIR}/ceph.sources"
readonly PVE_NO_SUB_SOURCE="${SOURCES_DIR}/pve-no-subscription.sources"
readonly CEPH_NO_SUB_SOURCE="${SOURCES_DIR}/ceph-no-subscription.sources"

usage() {
  cat <<'EOF'
Usage: proxmox-enable-no-subscription-repos.sh --apply

Replaces the Proxmox VE and Ceph enterprise APT sources with the official
no-subscription sources on a Proxmox VE 9 / Debian 13 (Trixie) host.

The original source files are retained in a timestamped backup beneath /root.
EOF
}

if [[ "${MODE}" != "--apply" ]]; then
  usage
  exit 2
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: run this script as root." >&2
  exit 1
fi

for command_name in apt-get date grep install mktemp mv pveversion; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  fi
done

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "debian" || "${VERSION_CODENAME:-}" != "trixie" ]]; then
  echo "ERROR: this script is restricted to Debian 13 (Trixie)." >&2
  exit 1
fi

if ! pveversion | grep -Eq '^pve-manager/9\.'; then
  echo "ERROR: this script is restricted to Proxmox VE 9." >&2
  exit 1
fi

for source_file in "${PVE_ENTERPRISE_SOURCE}" "${CEPH_ENTERPRISE_SOURCE}"; do
  if [[ ! -f "${source_file}" ]]; then
    echo "ERROR: expected source file not found: ${source_file}" >&2
    exit 1
  fi
done

for source_file in "${PVE_NO_SUB_SOURCE}" "${CEPH_NO_SUB_SOURCE}"; do
  if [[ -e "${source_file}" ]]; then
    echo "ERROR: refusing to overwrite existing source file: ${source_file}" >&2
    exit 1
  fi
done

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly TIMESTAMP
readonly BACKUP_DIR="/root/pve-apt-sources-before-no-subscription-${TIMESTAMP}"
readonly PVE_DISABLED_SOURCE="${BACKUP_DIR}/pve-enterprise.sources.disabled"
readonly CEPH_DISABLED_SOURCE="${BACKUP_DIR}/ceph.sources.disabled"
PVE_TEMP_SOURCE="$(mktemp "${SOURCES_DIR}/.pve-no-subscription.XXXXXX")"
CEPH_TEMP_SOURCE="$(mktemp "${SOURCES_DIR}/.ceph-no-subscription.XXXXXX")"

cleanup_temporary_files() {
  rm -f -- "${PVE_TEMP_SOURCE}" "${CEPH_TEMP_SOURCE}"
}
trap cleanup_temporary_files EXIT

install -d -m 0700 "${BACKUP_DIR}"

cat >"${PVE_TEMP_SOURCE}" <<'EOF'
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF

cat >"${CEPH_TEMP_SOURCE}" <<'EOF'
Types: deb
URIs: http://download.proxmox.com/debian/ceph-squid
Suites: trixie
Components: no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF

mv -- "${PVE_ENTERPRISE_SOURCE}" "${PVE_DISABLED_SOURCE}"
mv -- "${CEPH_ENTERPRISE_SOURCE}" "${CEPH_DISABLED_SOURCE}"
install -m 0644 "${PVE_TEMP_SOURCE}" "${PVE_NO_SUB_SOURCE}"
install -m 0644 "${CEPH_TEMP_SOURCE}" "${CEPH_NO_SUB_SOURCE}"

rollback_repository_files() {
  echo "APT update failed; restoring the original repository files." >&2
  rm -f -- "${PVE_NO_SUB_SOURCE}" "${CEPH_NO_SUB_SOURCE}"
  mv -- "${PVE_DISABLED_SOURCE}" "${PVE_ENTERPRISE_SOURCE}"
  mv -- "${CEPH_DISABLED_SOURCE}" "${CEPH_ENTERPRISE_SOURCE}"
}

if ! apt-get update; then
  rollback_repository_files
  exit 1
fi

if grep -RIl --include='*.sources' --include='*.list' \
  'enterprise\.proxmox\.com' "${SOURCES_DIR}"; then
  echo "ERROR: an active enterprise.proxmox.com source remains configured." >&2
  exit 1
fi

echo "REPOSITORY_MODE=no-subscription"
echo "APT_UPDATE=passed"
echo "SOURCE_BACKUP_DIRECTORY=${BACKUP_DIR}"
echo "DISABLED_PVE_SOURCE=${PVE_DISABLED_SOURCE}"
echo "DISABLED_CEPH_SOURCE=${CEPH_DISABLED_SOURCE}"
