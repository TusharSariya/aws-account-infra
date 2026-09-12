#!/usr/bin/env bash

# Collect a read-only IBM ServeRAID/MegaRAID health report on Proxmox.
# Usage: ./proxmox-serveraid-inspect.sh [output-directory]

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

for required_command in awk date grep install lspci tar uname; do
  command -v "$required_command" >/dev/null 2>&1 \
    || fail "required command is unavailable: $required_command"
done

REPORT_TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly REPORT_TIMESTAMP
readonly REPORT_NAME="pve-serveraid-inspection-${REPORT_TIMESTAMP}"
readonly REPORT_DIRECTORY="${OUTPUT_DIRECTORY%/}/${REPORT_NAME}"
readonly REPORT_ARCHIVE="${REPORT_DIRECTORY}.tar.gz"

[[ ! -e "$REPORT_DIRECTORY" ]] || fail "report directory already exists: $REPORT_DIRECTORY"
[[ ! -e "$REPORT_ARCHIVE" ]] || fail "report archive already exists: $REPORT_ARCHIVE"

install -d -m 0700 "$REPORT_DIRECTORY"

uname -a >"$REPORT_DIRECTORY/uname.txt"
lspci -nnk >"$REPORT_DIRECTORY/pci-devices.txt"

if command -v pveversion >/dev/null 2>&1; then
  pveversion -v >"$REPORT_DIRECTORY/pve-version.txt"
fi

if command -v dmesg >/dev/null 2>&1; then
  dmesg -T 2>/dev/null \
    | grep -Ei '(megaraid|megaraid_sas|serveraid|sas|scsi|raid)' \
    >"$REPORT_DIRECTORY/storage-kernel-messages.txt" || true
fi

RAID_CLI=""
RAID_CLI_KIND=""

readonly STORCLI_PATHS=(
  /opt/MegaRAID/storcli/storcli64
  /opt/MegaRAID/storcli/storcli
  /opt/MegaRAID/perccli/perccli64
  /opt/MegaRAID/perccli/perccli
)

for cli_path in "${STORCLI_PATHS[@]}"; do
  if [[ -x "$cli_path" ]]; then
    RAID_CLI="$cli_path"
    RAID_CLI_KIND="storcli"
    break
  fi
done

if [[ -z "$RAID_CLI" ]]; then
  for cli_name in storcli64 storcli perccli64 perccli; do
    if command -v "$cli_name" >/dev/null 2>&1; then
      RAID_CLI="$(command -v "$cli_name")"
      RAID_CLI_KIND="storcli"
      break
    fi
  done
fi

if [[ -z "$RAID_CLI" ]]; then
  readonly MEGACLI_PATHS=(
    /opt/MegaRAID/MegaCli/MegaCli64
    /opt/MegaRAID/MegaCli/MegaCli
    /usr/sbin/MegaCli64
    /usr/sbin/MegaCli
  )

  for cli_path in "${MEGACLI_PATHS[@]}"; do
    if [[ -x "$cli_path" ]]; then
      RAID_CLI="$cli_path"
      RAID_CLI_KIND="megacli"
      break
    fi
  done
fi

if [[ -z "$RAID_CLI" ]]; then
  for cli_name in MegaCli64 MegaCli megacli; do
    if command -v "$cli_name" >/dev/null 2>&1; then
      RAID_CLI="$(command -v "$cli_name")"
      RAID_CLI_KIND="megacli"
      break
    fi
  done
fi

if [[ -z "$RAID_CLI" ]]; then
  printf 'RAID_CLI=not-found\n'
  printf 'REPORT_DIRECTORY=%s\n' "$REPORT_DIRECTORY"
  printf 'The PCI and kernel evidence was retained. Install IBM/Broadcom StorCLI '
  printf 'for Linux, then rerun this script.\n'
  exit 3
fi

readonly RAID_CLI
readonly RAID_CLI_KIND

RUN_FAILURES=()

run_report() {
  local report_name="$1"
  local requirement="$2"
  shift 2

  {
    printf 'COMMAND:'
    printf ' %q' "$@"
    printf '\n'
  } >>"$REPORT_DIRECTORY/commands.log"

  if "$@" >"$REPORT_DIRECTORY/${report_name}.txt" 2>&1; then
    printf '%s=collected\n' "$report_name" >>"$REPORT_DIRECTORY/collection-status.txt"
  else
    printf '%s=command-failed\n' "$report_name" \
      >>"$REPORT_DIRECTORY/collection-status.txt"
    if [[ "$requirement" == "required" ]]; then
      RUN_FAILURES+=("$report_name")
    fi
    return 1
  fi
}

PHYSICAL_LIST_REPORT=""
SMART_REPORTS=()

if [[ "$RAID_CLI_KIND" == "storcli" ]]; then
  run_report cli-version optional "$RAID_CLI" show || true
  run_report controller-all required "$RAID_CLI" /call show all || true
  run_report virtual-drives required "$RAID_CLI" /call /vall show all || true
  run_report patrol-read required "$RAID_CLI" /call show patrolread || true
  run_report consistency-check-state optional "$RAID_CLI" /call show cc || true
  run_report battery-backup optional "$RAID_CLI" /call /bbu show all || true
  run_report cachevault optional "$RAID_CLI" /call /cv show all || true

  if run_report physical-list-enclosures optional \
    "$RAID_CLI" /call /eall /sall show; then
    PHYSICAL_LIST_REPORT="$REPORT_DIRECTORY/physical-list-enclosures.txt"
  elif run_report physical-list-direct optional \
    "$RAID_CLI" /call /sall show; then
    PHYSICAL_LIST_REPORT="$REPORT_DIRECTORY/physical-list-direct.txt"
  else
    RUN_FAILURES+=("physical-list")
  fi

  if ! run_report physical-details-enclosures optional \
    "$RAID_CLI" /call /eall /sall show all; then
    run_report physical-details-direct required \
      "$RAID_CLI" /call /sall show all || true
  fi
else
  run_report controller-all required \
    "$RAID_CLI" -AdpAllInfo -aALL || true
  run_report virtual-drives required \
    "$RAID_CLI" -LDInfo -Lall -aALL || true
  run_report physical-details required \
    "$RAID_CLI" -PDList -aALL || true
  run_report patrol-read required \
    "$RAID_CLI" -AdpPR -Info -aALL || true
  run_report battery-backup optional \
    "$RAID_CLI" -AdpBbuCmd -GetBbuStatus -aALL || true
fi

if command -v smartctl >/dev/null 2>&1; then
  SMART_SCAN_REPORT="$REPORT_DIRECTORY/smart-scan.txt"
  if smartctl --scan-open >"$SMART_SCAN_REPORT" 2>&1; then
    printf 'smart-scan=collected\n' >>"$REPORT_DIRECTORY/collection-status.txt"

    while read -r smart_device smart_flag smart_type _; do
      [[ "$smart_flag" == "-d" ]] || continue
      [[ "$smart_device" =~ ^/dev/[A-Za-z0-9_./-]+$ ]] || continue
      [[ "$smart_type" =~ ^megaraid,[0-9]+$ ]] || continue

      smart_device_id="${smart_type#megaraid,}"
      smart_report_name="smart-megaraid-${smart_device_id}"
      if run_report "$smart_report_name" required \
        smartctl -q noserial -a -d "$smart_type" "$smart_device"; then
        SMART_REPORTS+=("$REPORT_DIRECTORY/${smart_report_name}.txt")
      fi
    done <"$SMART_SCAN_REPORT"

    expected_physical_count=0
    if [[ -n "$PHYSICAL_LIST_REPORT" ]]; then
      expected_physical_count="$(
        awk '$1 ~ /^[0-9]+:[0-9]+$/ { count++ } END { print count + 0 }' \
          "$PHYSICAL_LIST_REPORT"
      )"
    fi

    if (( expected_physical_count == 0 )); then
      RUN_FAILURES+=("smart-physical-count-unavailable")
    elif (( ${#SMART_REPORTS[@]} != expected_physical_count )); then
      printf 'smart-coverage=count-mismatch expected=%d collected=%d\n' \
        "$expected_physical_count" "${#SMART_REPORTS[@]}" \
        >>"$REPORT_DIRECTORY/collection-status.txt"
      RUN_FAILURES+=("smart-coverage")
    else
      printf 'smart-coverage=complete count=%d\n' "$expected_physical_count" \
        >>"$REPORT_DIRECTORY/collection-status.txt"
    fi
  else
    printf 'smart-scan=command-failed\n' \
      >>"$REPORT_DIRECTORY/collection-status.txt"
    RUN_FAILURES+=("smart-scan")
  fi
else
  printf 'smartctl=not-found\n' >>"$REPORT_DIRECTORY/collection-status.txt"
  RUN_FAILURES+=("smartctl-not-found")
fi

{
  printf 'RAID_CLI=%s\n' "$RAID_CLI"
  printf 'RAID_CLI_KIND=%s\n' "$RAID_CLI_KIND"
  printf '\nCOLLECTION STATUS\n'
  cat "$REPORT_DIRECTORY/collection-status.txt"

  if [[ -n "$PHYSICAL_LIST_REPORT" ]]; then
    printf '\nPHYSICAL DRIVE LIST\n'
    cat "$PHYSICAL_LIST_REPORT"
  fi

  printf '\nHEALTH AND POLICY FIELDS\n'
  grep -RhiE \
    '^(Controller|Status|Description|Product Name|FW Package Build|RAID Level|State|Current Cache Policy|Default Cache Policy|Disk Cache Policy|Shield Counter|BBM Error Count|Media Error Count|Other Error Count|Predictive Failure Count|S\.M\.A\.R\.T alert flagged by drive|Battery State|Replacement required|Pack is about to fail|Capacitance|PR Mode|Patrol Read|PR status)' \
    "$REPORT_DIRECTORY"/*.txt 2>/dev/null || true

  if (( ${#SMART_REPORTS[@]} > 0 )); then
    printf '\nSMART HEALTH BY MEGARAID DEVICE ID\n'
    for smart_report in "${SMART_REPORTS[@]}"; do
      printf 'SMART_REPORT=%s\n' "${smart_report##*/}"
      grep -Ei \
        '^(SMART Health Status|Elements in grown defect list|Non-medium error count)' \
        "$smart_report" || true
    done
  fi
} >"$REPORT_DIRECTORY/shareable-summary.txt"

tar \
  --numeric-owner \
  -C "$OUTPUT_DIRECTORY" \
  -czf "$REPORT_ARCHIVE" \
  "$REPORT_NAME"
chmod 0600 "$REPORT_ARCHIVE"

printf 'RAID_CLI=%s\n' "$RAID_CLI"
printf 'REPORT_DIRECTORY=%s\n' "$REPORT_DIRECTORY"
printf 'REPORT_ARCHIVE=%s\n' "$REPORT_ARCHIVE"

if (( ${#RUN_FAILURES[@]} > 0 )); then
  printf 'COLLECTION_STATUS=incomplete\n'
  printf 'REQUIRED_FAILURES=%s\n' "${RUN_FAILURES[*]}"
  printf 'Review %s and rerun after resolving the command failures.\n' \
    "$REPORT_DIRECTORY/collection-status.txt"
  exit 4
fi

printf 'COLLECTION_STATUS=complete\n'
printf 'SHAREABLE_SUMMARY_BEGIN\n'
cat "$REPORT_DIRECTORY/shareable-summary.txt"
printf 'SHAREABLE_SUMMARY_END\n'
