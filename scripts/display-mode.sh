#!/usr/bin/env bash
#
# Temporarily stop the graphical stack on an Ubuntu host, and put it back.
#
# NOTHING THIS SCRIPT DOES SURVIVES A REBOOT. It only ever calls `systemctl
# stop` and `systemctl start`. It must never call `disable`, `mask`, or
# `set-default`, and must never touch /etc/systemd/system/display-manager.service
# -- those are the only ways to make the change outlive a reboot. State lives in
# /run, which is tmpfs, so it is destroyed on boot by construction.
#
# Scope is deliberately two units: the display manager and the greeter's user
# manager. An earlier draft also stopped ~16 daemons and 19 timers; review cut
# all of it. See the "What was cut and why" section of the plan before adding
# anything back -- several of those units are load-bearing (sssd backs PAM/NSS
# on the console recovery path) or leave persistent state when interrupted
# (snapd mid-refresh).
#
# Run on the Ubuntu host as root:
#   sudo /usr/local/sbin/display-mode --disable
#
set -euo pipefail

readonly STATE_FILE="${DISPLAY_MODE_STATE:-/run/display-mode.state}"
readonly LOCK_FILE="${DISPLAY_MODE_LOCK:-/run/display-mode.lock}"
readonly DM_UNIT="display-manager.service"
readonly DETACH_UNIT="display-mode-disable"

# Indirection so the bats suite can inject fixtures instead of touching the host.
SYSTEMCTL="${DISPLAY_MODE_SYSTEMCTL:-systemctl}"
LOGINCTL="${DISPLAY_MODE_LOGINCTL:-loginctl}"
GETENT="${DISPLAY_MODE_GETENT:-getent}"
NVIDIA_SMI="${DISPLAY_MODE_NVIDIA_SMI:-nvidia-smi}"
FREE="${DISPLAY_MODE_FREE:-free}"
NPROC="${DISPLAY_MODE_NPROC:-nproc}"

# Seconds between CPU samples. The reported figure is ~0.16% of one core, so
# this is a long wait for a small number -- kept because it was explicitly
# requested, skipped entirely in --dry-run.
readonly CPU_SAMPLE_SECONDS="${DISPLAY_MODE_CPU_SAMPLE_SECONDS:-10}"

die() { printf 'display-mode: %s\n' "$*" >&2; exit 1; }
info() { printf '%s\n' "$*"; }

usage() {
  cat <<'EOF'
Usage: display-mode <action>

  --disable    Stop the display manager and greeter. Prints what was freed.
  --enable     Restart whatever --disable recorded.
  --status     Current mode, recorded units, recorded savings.
  --dry-run    Show what would be stopped. Changes nothing. Returns immediately.
  --force      With --disable: proceed despite an active local desktop session
               or a running GPU workload.
  --help       This text.

Nothing is permanent. A reboot restores the desktop even if --enable is never
run, because no unit is ever disabled and state lives in tmpfs.
EOF
}

require_root() {
  [ "${EUID:-$(id -u)}" -eq 0 ] ||
    die "must run as root, e.g. sudo /usr/local/sbin/display-mode ${1:---status}"
}

unit_active() { "$SYSTEMCTL" is-active --quiet "$1" 2>/dev/null; }

unit_exists() {
  "$SYSTEMCTL" cat "$1" >/dev/null 2>&1 ||
    [ "$("$SYSTEMCTL" show "$1" -p LoadState --value 2>/dev/null)" = "loaded" ]
}

# The invoking human's uid. Under sudo this is SUDO_UID; without it we are
# already root and fall back to 1000, the conventional first human account.
# Used only as a guard -- we refuse to stop this user's session manager.
invoking_uid() { printf '%s' "${SUDO_UID:-1000}"; }

# Resolve the greeter's user-manager uid.
#
# This is the single most dangerous lookup in the script. `id -u gdm` is WRONG
# on Ubuntu 26: it returns the gdm service account (975), while the greeter
# session -- and the ~572 MB that makes this script worth running -- belongs to
# a separate `gdm-greeter` account (60578). Getting it wrong either saves
# nothing or stops the invoking user's own session.
#
# Primary source is loginctl Class=greeter, which is semantic rather than
# name-based. Falls back to running user@*.service minus the invoking uid,
# gated on the account name looking like a gdm account.
resolve_greeter_uid() {
  local sid uid class candidates=() me
  me="$(invoking_uid)"

  while read -r sid _; do
    [ -n "$sid" ] || continue
    class="$("$LOGINCTL" show-session "$sid" -p Class --value 2>/dev/null || true)"
    uid="$("$LOGINCTL" show-session "$sid" -p User --value 2>/dev/null || true)"
    [ "$class" = "greeter" ] || continue
    [ -n "$uid" ] || continue
    [ "$uid" != "$me" ] || continue
    candidates+=("$uid")
  done < <("$LOGINCTL" list-sessions --no-legend 2>/dev/null || true)

  if [ "${#candidates[@]}" -eq 0 ]; then
    local name
    while read -r unit _; do
      uid="${unit#user@}"; uid="${uid%.service}"
      [[ "$uid" =~ ^[0-9]+$ ]] || continue
      [ "$uid" != "$me" ] || continue
      name="$("$GETENT" passwd "$uid" 2>/dev/null | cut -d: -f1)"
      [[ "$name" == gdm* ]] || continue
      candidates+=("$uid")
    done < <("$SYSTEMCTL" list-units 'user@*.service' --state=running \
               --no-legend --no-pager 2>/dev/null || true)
  fi

  # Deduplicate: a greeter can hold more than one session (seat0 plus a
  # manager session), and both map to the same uid.
  printf '%s\n' "${candidates[@]+"${candidates[@]}"}" | sort -u | sed '/^$/d'
}

# Guard the resolved uid before it is ever handed to `systemctl stop`.
assert_greeter_uid() {
  local uid="$1"
  [ -n "$uid" ] || die "could not resolve a greeter session; is the desktop already stopped?"
  [ "$(printf '%s' "$uid" | wc -l)" -eq 0 ] ||
    die "ambiguous greeter uid (multiple candidates): $(echo "$uid" | tr '\n' ' ')"
  [[ "$uid" =~ ^[0-9]+$ ]] || die "greeter uid is not numeric: '$uid'"
  [ "$uid" != "1000" ] || die "refusing: resolved greeter uid is 1000, a human account"
  [ "$uid" != "$(invoking_uid)" ] ||
    die "refusing: resolved greeter uid $uid is the invoking user"
  [ "$uid" != "0" ] || die "refusing: resolved greeter uid is root"
  printf '%s' "$uid"
}

# The ordered unit list. Display manager first so its session tears down
# cleanly before we touch the manager that hosts it.
target_units() {
  local uid
  uid="$(assert_greeter_uid "$(resolve_greeter_uid)")"
  printf '%s\n' "$DM_UNIT" "user@${uid}.service"
}

mem_available_mb() { "$FREE" -m | awk '/^Mem:/{print $7}'; }
mem_total_mb() { "$FREE" -m | awk '/^Mem:/{print $2}'; }

vram_used_mib() {
  command -v "$NVIDIA_SMI" >/dev/null 2>&1 || { printf ''; return; }
  "$NVIDIA_SMI" --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1
}

gpu_compute_procs() {
  command -v "$NVIDIA_SMI" >/dev/null 2>&1 || { printf '0'; return; }
  "$NVIDIA_SMI" --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c . || true
}

unit_mem_mb() {
  local v
  v="$("$SYSTEMCTL" show "$1" -p MemoryCurrent --value 2>/dev/null || true)"
  case "$v" in ''|'[not set]'|18446744073709551615) printf '0' ;; *) printf '%s' "$((v / 1024 / 1024))" ;; esac
}

unit_cpu_nsec() {
  local v
  v="$("$SYSTEMCTL" show "$1" -p CPUUsageNSec --value 2>/dev/null || true)"
  case "$v" in ''|'[not set]') printf '0' ;; *) printf '%s' "$v" ;; esac
}

# Stopping the display manager removes the last DRM client. Without persistence
# mode the NVIDIA driver tears down and re-initialises, which adds latency to
# the next CUDA init and can transiently perturb what the device plugin
# advertises on a node carrying nvidia.com/gpu.
check_gpu_preconditions() {
  local force="$1" procs mode
  command -v "$NVIDIA_SMI" >/dev/null 2>&1 || return 0

  # Query persistence mode directly rather than trusting nvidia-persistenced's
  # unit state. Measured on this host: the service reports `active` while
  # persistence mode is `Disabled`, so the service check alone is a false pass.
  mode="$("$NVIDIA_SMI" --query-gpu=persistence_mode --format=csv,noheader 2>/dev/null |
            head -1 | tr -d '[:space:]')"
  if [ "$mode" != "Enabled" ]; then
    if [ "$force" != "yes" ]; then
      die "GPU persistence mode is '${mode:-unknown}'; stopping the display manager removes
  the last DRM client and the driver will tear down and re-initialise. That adds
  latency to the next CUDA init and can perturb what the device plugin advertises.
  Fix with: nvidia-smi -pm 1     (runtime only; resets on reboot)
  Override with --force."
    fi
    info "WARNING: GPU persistence mode is '${mode:-unknown}'; driver will re-initialise (--force)."
  fi

  procs="$(gpu_compute_procs)"
  if [ "$procs" -gt 0 ] && [ "$force" != "yes" ]; then
    die "$procs GPU compute process(es) running; refusing to tear down the display stack.
  Override with --force."
  fi
}

# Refuse to kill a logged-in desktop session unless told to. The gdm greeter
# alone (Class=greeter) does not count -- that is what we are here to stop.
check_local_session() {
  local force="$1" sid class seat active=0
  while read -r sid _; do
    [ -n "$sid" ] || continue
    class="$("$LOGINCTL" show-session "$sid" -p Class --value 2>/dev/null || true)"
    seat="$("$LOGINCTL" show-session "$sid" -p Seat --value 2>/dev/null || true)"
    [ "$class" = "user" ] && [ -n "$seat" ] && active=$((active + 1))
  done < <("$LOGINCTL" list-sessions --no-legend 2>/dev/null || true)

  if [ "$active" -gt 0 ] && [ "$force" != "yes" ]; then
    die "$active active local desktop session(s) would be terminated. Override with --force."
  fi
}

state_write() {
  local tmp
  tmp="$(mktemp "${STATE_FILE}.XXXXXX")"
  cat >"$tmp"
  # Atomic replace, so a reader never sees a half-written file and a crash
  # mid-write cannot corrupt an existing snapshot.
  mv -f "$tmp" "$STATE_FILE"
}

in_compute_mode() { [ -f "$STATE_FILE" ]; }

do_dry_run() {
  local units unit
  units="$(target_units)"
  info "Would stop (nothing is being changed):"
  while read -r unit; do
    [ -n "$unit" ] || continue
    if unit_active "$unit"; then
      printf '  %-32s active    %5s MB   restored by: %s\n' \
        "$unit" "$(unit_mem_mb "$unit")" "$("$SYSTEMCTL" is-enabled "$unit" 2>/dev/null || echo 'graphical.target')"
    else
      printf '  %-32s inactive  (skipped)\n' "$unit"
    fi
  done <<<"$units"
  info ""
  info "State file: $STATE_FILE (tmpfs; a reboot restores the desktop regardless)"
}

do_disable() {
  local force="$1" units unit mem_before mem_after vram_before vram_after
  local -a stopped=() cpu_before=() cpu_delta=()

  if in_compute_mode; then
    info "Already in compute mode (state: $STATE_FILE). Nothing to do."
    return 0
  fi

  units="$(target_units)"
  check_local_session "$force"
  check_gpu_preconditions "$force"

  # Sample CPU before stopping. Cumulative counters reset when a unit restarts,
  # so a negative delta is discarded rather than reported.
  local i=0
  while read -r unit; do
    [ -n "$unit" ] || continue
    cpu_before[i]="$(unit_cpu_nsec "$unit")"
    i=$((i + 1))
  done <<<"$units"
  info "Sampling CPU for ${CPU_SAMPLE_SECONDS}s..."
  sleep "$CPU_SAMPLE_SECONDS"
  i=0
  while read -r unit; do
    [ -n "$unit" ] || continue
    local after delta
    after="$(unit_cpu_nsec "$unit")"
    delta=$((after - cpu_before[i]))
    [ "$delta" -lt 0 ] && delta=0
    cpu_delta[i]="$delta"
    i=$((i + 1))
  done <<<"$units"

  mem_before="$(mem_available_mb)"
  vram_before="$(vram_used_mib)"

  # Snapshot intent BEFORE any mutation. Starting an already-running unit is a
  # no-op, so recording intent up front is strictly safer than recording after
  # the fact: if the script dies mid-teardown, --enable still knows the full set.
  {
    printf 'phase=stopping\n'
    printf 'mem_available_before=%s\n' "$mem_before"
    printf 'vram_used_before=%s\n' "${vram_before:-}"
    while read -r unit; do
      [ -n "$unit" ] || continue
      unit_active "$unit" && printf 'unit=%s\n' "$unit"
    done <<<"$units"
  } | state_write

  while read -r unit; do
    [ -n "$unit" ] || continue
    # Never stop a unit that is not running: under `set -e` a failed stop on an
    # absent unit aborts the script after the desktop is already down. Do not
    # swap this for `|| true`, which would also swallow genuine failures.
    if ! unit_active "$unit"; then
      info "  skip     $unit (not active)"
      continue
    fi
    info "  stopping $unit"
    "$SYSTEMCTL" stop "$unit"
    stopped+=("$unit")
  done <<<"$units"

  # Poll to confirmed-inactive rather than sleeping a guessed interval, so the
  # memory reading reflects actual reclaim.
  local waited=0
  while [ "$waited" -lt 15 ]; do
    local still=0
    for unit in ${stopped[@]+"${stopped[@]}"}; do unit_active "$unit" && still=1; done
    [ "$still" -eq 0 ] && break
    sleep 1; waited=$((waited + 1))
  done

  mem_after="$(mem_available_mb)"
  vram_after="$(vram_used_mib)"

  { cat "$STATE_FILE"; printf 'phase=stopped\nmem_available_after=%s\nvram_used_after=%s\n' \
      "$mem_after" "${vram_after:-}"; } | grep -v '^phase=stopping$' | state_write

  info ""
  info "Freed:"
  printf '  RAM   %s MB available -> %s MB  (+%s MB of %s MB total)\n' \
    "$mem_before" "$mem_after" "$((mem_after - mem_before))" "$(mem_total_mb)"
  if [ -n "${vram_before:-}" ] && [ -n "${vram_after:-}" ]; then
    printf '  VRAM  %s MiB used -> %s MiB  (-%s MiB)\n' \
      "$vram_before" "$vram_after" "$((vram_before - vram_after))"
  fi
  i=0
  while read -r unit; do
    [ -n "$unit" ] || continue
    printf '  CPU   %-30s %s%% of one core\n' "$unit" \
      "$(awk -v d="${cpu_delta[i]}" -v s="$CPU_SAMPLE_SECONDS" 'BEGIN{printf "%.3f", d/(s*1e9)*100}')"
    i=$((i + 1))
  done <<<"$units"
  info ""
  info "CPU reclaim here is real but negligible: kubelet and containerd alone run"
  info "~21% of one core out of $("$NPROC"). The win is RAM and fewer moving parts."
  info ""
  info "Restore with: display-mode --enable   (a reboot also restores it)"
}

do_enable() {
  local unit restored=0
  if ! in_compute_mode; then
    info "Not in compute mode; nothing recorded to restore."
    return 0
  fi
  # Reverse order: the user manager comes back before the display manager that
  # will populate it.
  while read -r unit; do
    [ -n "$unit" ] || continue
    if unit_active "$unit"; then
      info "  already running $unit"
    else
      info "  starting $unit"
      "$SYSTEMCTL" start "$unit"
    fi
    restored=$((restored + 1))
  done < <(grep '^unit=' "$STATE_FILE" | sed 's/^unit=//' | tac)

  rm -f "$STATE_FILE"
  info ""
  info "Restored $restored unit(s). RAM available now: $(mem_available_mb) MB"
}

do_status() {
  if ! in_compute_mode; then
    info "Mode:    desktop (normal)"
    printf 'Display: %s\n' "$(unit_active "$DM_UNIT" && echo active || echo inactive)"
    info "State:   none ($STATE_FILE absent)"
    return 0
  fi
  info "Mode:    compute (display stopped)"
  info "Stopped units:"
  grep '^unit=' "$STATE_FILE" | sed 's/^unit=/  /'
  info "Recorded:"
  grep -E '^(mem_available|vram_used|phase)' "$STATE_FILE" | sed 's/^/  /'
  printf 'RAM available now: %s MB\n' "$(mem_available_mb)"
  info ""
  info "Restore with: display-mode --enable   (a reboot also restores it)"
}

main() {
  local action="" force="no" arg
  [ "$#" -gt 0 ] || { usage; exit 2; }

  for arg in "$@"; do
    case "$arg" in
      --disable|--enable|--status|--dry-run) action="$arg" ;;
      --force) force="yes" ;;
      --help|-h) usage; exit 0 ;;
      *) usage; die "unknown argument: $arg" ;;
    esac
  done
  [ -n "$action" ] || { usage; exit 2; }

  if [ "$action" = "--dry-run" ] || [ "$action" = "--status" ]; then
    require_root "$action"
    if [ "$action" = "--dry-run" ]; then do_dry_run; else do_status; fi
    return 0
  fi

  require_root "$action"

  # Serialise: two concurrent invocations must not interleave stops and starts.
  exec 9>"$LOCK_FILE"
  flock -n 9 || die "another display-mode invocation holds $LOCK_FILE"

  # Re-exec detached so an SSH drop cannot SIGHUP the script mid-teardown and
  # strand the box with the desktop down. --pipe keeps output on the terminal.
  if [ "${DISPLAY_MODE_DETACHED:-}" != "1" ] && command -v systemd-run >/dev/null 2>&1; then
    flock -u 9
    exec systemd-run --collect --unit="$DETACH_UNIT" --wait --pipe --quiet \
      --setenv=DISPLAY_MODE_DETACHED=1 \
      "$(readlink -f "$0")" "$@"
  fi

  case "$action" in
    --disable) do_disable "$force" ;;
    --enable)  do_enable ;;
  esac
}

# Guard so the bats suite can source this file for unit testing without
# executing anything.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  main "$@"
fi
