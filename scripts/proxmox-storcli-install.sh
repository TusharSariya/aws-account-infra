#!/usr/bin/env bash
set -euo pipefail

readonly MODE="${1:-}"
readonly PACKAGE_URL="https://download2.boulder.ibm.com/sar/CMA/XSA/08uow/0/ibm_utl_sraidmr_storcli-7.1212.0000.0000_linux_32-64.tgz"
readonly PACKAGE_NAME="ibm_utl_sraidmr_storcli-7.1212.0000.0000_linux_32-64.tgz"
readonly PACKAGE_SHA256="a33b2696df36c4a56c1e8a8217ba90eb698de5a4498d58a8268c862cab4639fe"
readonly PACKAGE_SIZE_BYTES="4002328"
readonly RPM_NAME="storcli-007.1212.0000.0000-1.noarch.rpm"
readonly DESTINATION_DIRECTORY="/opt/MegaRAID/storcli"
readonly DESTINATION_BINARY="${DESTINATION_DIRECTORY}/storcli64"

usage() {
  cat <<'EOF'
Usage: proxmox-storcli-install.sh --apply

Downloads the IBM StorCLI 7.1212 package pinned for the ServeRAID M5110,
verifies the archive digest and embedded RPM signature, then installs only
the 64-bit StorCLI binary at /opt/MegaRAID/storcli/storcli64.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ "${MODE}" == "--apply" ]] || {
  usage
  exit 2
}

(( EUID == 0 )) || fail "run this script as root on the Proxmox host"

for command_name in apt-get awk cpio curl date file grep install rpm rpm2cpio \
  sha256sum stat tar; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    if [[ "${command_name}" == "rpm" || "${command_name}" == "rpm2cpio" \
      || "${command_name}" == "cpio" ]]; then
      continue
    fi
    fail "required command is unavailable: ${command_name}"
  fi
done

[[ ! -e "${DESTINATION_BINARY}" ]] \
  || fail "refusing to overwrite existing binary: ${DESTINATION_BINARY}"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly TIMESTAMP
readonly WORK_DIRECTORY="/root/pve-storcli-install-${TIMESTAMP}"
readonly ARCHIVE_PATH="${WORK_DIRECTORY}/${PACKAGE_NAME}"
readonly EXTRACT_DIRECTORY="${WORK_DIRECTORY}/archive"
readonly RPM_EXTRACT_DIRECTORY="${WORK_DIRECTORY}/rpm-payload"
readonly RPM_DATABASE_DIRECTORY="${WORK_DIRECTORY}/rpm-database"
readonly RPM_POLICY_PATH="${WORK_DIRECTORY}/rpm-legacy-binding-policy.toml"

install -d -m 0700 "${WORK_DIRECTORY}" "${EXTRACT_DIRECTORY}" \
  "${RPM_EXTRACT_DIRECTORY}" "${RPM_DATABASE_DIRECTORY}"

curl --fail --silent --show-error --location \
  --output "${ARCHIVE_PATH}" "${PACKAGE_URL}"

actual_size="$(stat --format='%s' "${ARCHIVE_PATH}")"
[[ "${actual_size}" == "${PACKAGE_SIZE_BYTES}" ]] \
  || fail "archive size mismatch: expected ${PACKAGE_SIZE_BYTES}, got ${actual_size}"

printf '%s  %s\n' "${PACKAGE_SHA256}" "${ARCHIVE_PATH}" | sha256sum --check

if tar -tzf "${ARCHIVE_PATH}" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
  fail "archive contains an unsafe path"
fi
tar -xzf "${ARCHIVE_PATH}" -C "${EXTRACT_DIRECTORY}"

readonly RPM_PATH="${EXTRACT_DIRECTORY}/${RPM_NAME}"
readonly PUBLIC_KEY_PATH="${EXTRACT_DIRECTORY}/pubKey.asc"
[[ -f "${RPM_PATH}" ]] || fail "expected RPM is missing: ${RPM_NAME}"
[[ -f "${PUBLIC_KEY_PATH}" ]] || fail "embedded RPM public key is missing"

apt-get install -y --no-install-recommends cpio rpm rpm2cpio

# IBM's 2019 key uses a legacy SHA-1 certificate binding. Permit SHA-1 only
# for second-preimage-resistant contexts such as that binding. This does not
# permit SHA-1 payload signatures and does not alter the host's global policy.
cat >"${RPM_POLICY_PATH}" <<'EOF'
[hash_algorithms]
sha1.second_preimage_resistance = "always"
EOF

RPM_SEQUOIA_CRYPTO_POLICY="${RPM_POLICY_PATH}" \
  SEQUOIA_CRYPTO_POLICY="${RPM_POLICY_PATH}" \
  rpm --dbpath "${RPM_DATABASE_DIRECTORY}" --initdb
RPM_SEQUOIA_CRYPTO_POLICY="${RPM_POLICY_PATH}" \
  SEQUOIA_CRYPTO_POLICY="${RPM_POLICY_PATH}" \
  rpm --dbpath "${RPM_DATABASE_DIRECTORY}" --import "${PUBLIC_KEY_PATH}"

signature_output="$({
  RPM_SEQUOIA_CRYPTO_POLICY="${RPM_POLICY_PATH}" \
    SEQUOIA_CRYPTO_POLICY="${RPM_POLICY_PATH}" \
    rpm --dbpath "${RPM_DATABASE_DIRECTORY}" --checksig --verbose "${RPM_PATH}"
} 2>&1)" || {
  printf '%s\n' "${signature_output}" >&2
  fail "RPM signature verification failed"
}
printf '%s\n' "${signature_output}"

if printf '%s\n' "${signature_output}" | grep -Eqi '(NOKEY|NOT OK|BAD)'; then
  fail "RPM signature output contains an unsafe result"
fi
if ! printf '%s\n' "${signature_output}" | grep -Eqi 'signature.*OK'; then
  fail "RPM signature output did not confirm a valid signature"
fi

(
  cd "${RPM_EXTRACT_DIRECTORY}"
  rpm2cpio "${RPM_PATH}" | cpio -idm --quiet --no-absolute-filenames
)

readonly EXTRACTED_BINARY="${RPM_EXTRACT_DIRECTORY}/opt/MegaRAID/storcli/storcli64"
[[ -f "${EXTRACTED_BINARY}" ]] || fail "the RPM does not contain storcli64"
file "${EXTRACTED_BINARY}" | grep -Eq 'ELF 64-bit.*x86-64' \
  || fail "storcli64 is not an x86-64 ELF binary"

install -d -m 0755 "${DESTINATION_DIRECTORY}"
install -m 0755 "${EXTRACTED_BINARY}" "${DESTINATION_BINARY}"

if ! "${DESTINATION_BINARY}" show >"${WORK_DIRECTORY}/storcli-show.txt" 2>&1; then
  rm -f -- "${DESTINATION_BINARY}"
  rmdir --ignore-fail-on-non-empty "${DESTINATION_DIRECTORY}" || true
  fail "StorCLI could not run; the installed binary was removed"
fi

echo "STORCLI_INSTALL=passed"
echo "STORCLI_PATH=${DESTINATION_BINARY}"
echo "PACKAGE_SHA256=${PACKAGE_SHA256}"
echo "RPM_POLICY_SCOPE=legacy-certificate-binding-only"
echo "INSTALL_EVIDENCE_DIRECTORY=${WORK_DIRECTORY}"
echo "ROLLBACK=rm -f ${DESTINATION_BINARY}"
