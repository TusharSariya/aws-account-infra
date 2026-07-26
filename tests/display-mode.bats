#!/usr/bin/env bats
#
# Unit tests for scripts/display-mode.sh.
#
# Everything here runs against injected fixtures -- no systemd, no real host
# state, safe in CI and safe on a laptop. The script is sourced rather than
# executed; its `BASH_SOURCE == $0` guard keeps main() from running.
#
# The cases that matter most are the greeter-UID guards. `id -u gdm` returns the
# gdm service account (975 on Ubuntu 26) while the greeter session belongs to
# gdm-greeter (60578). Resolving to the wrong uid either saves nothing or stops
# the invoking user's own session manager, so every rejection path is tested.

setup() {
  SCRIPT="${BATS_TEST_DIRNAME}/../scripts/display-mode.sh"
  export DISPLAY_MODE_STATE="${BATS_TEST_TMPDIR}/state"
  export DISPLAY_MODE_LOCK="${BATS_TEST_TMPDIR}/lock"
  export DISPLAY_MODE_CPU_SAMPLE_SECONDS=0
  export FIXTURE_DIR="${BATS_TEST_TMPDIR}/fixtures"
  mkdir -p "$FIXTURE_DIR"

  # Stub loginctl: reads sessions from $FIXTURE_DIR/sessions, formatted
  #   <sid> <uid> <class> <seat>
  cat >"${BATS_TEST_TMPDIR}/loginctl" <<'STUB'
#!/usr/bin/env bash
case "$1" in
  list-sessions) [ -f "$FIXTURE_DIR/sessions" ] && awk '{print $1" "$2}' "$FIXTURE_DIR/sessions" ;;
  show-session)
    sid="$2"; prop="${4:-}"
    line=$(awk -v s="$sid" '$1==s' "$FIXTURE_DIR/sessions" 2>/dev/null)
    [ -n "$line" ] || exit 1
    case "$prop" in
      Class) awk '{print $3}' <<<"$line" ;;
      User)  awk '{print $2}' <<<"$line" ;;
      Seat)  awk '{print $4}' <<<"$line" | sed 's/^-$//' ;;
    esac ;;
esac
STUB

  # Stub systemctl: active units listed in $FIXTURE_DIR/active, one per line.
  cat >"${BATS_TEST_TMPDIR}/systemctl" <<'STUB'
#!/usr/bin/env bash
active_file="$FIXTURE_DIR/active"
is_active() { [ -f "$active_file" ] && grep -qxF "$1" "$active_file"; }
case "$1" in
  is-active)
    unit="$3"; [ "$2" = "--quiet" ] || unit="$2"
    is_active "$unit" && exit 0 || exit 3 ;;
  stop)
    is_active "$2" || { echo "Unit $2 not loaded." >&2; exit 5; }
    grep -vxF "$2" "$active_file" > "$active_file.tmp" && mv "$active_file.tmp" "$active_file"
    echo "$2" >> "$FIXTURE_DIR/stopped" ;;
  start)
    echo "$2" >> "$active_file"; echo "$2" >> "$FIXTURE_DIR/started" ;;
  show)
    case "$*" in *CPUUsageNSec*) echo 1000000 ;; *MemoryCurrent*) echo 104857600 ;;
                 *LoadState*) echo loaded ;; *) echo "" ;; esac ;;
  is-enabled) echo enabled ;;
  list-units)
    [ -f "$FIXTURE_DIR/usermanagers" ] && cat "$FIXTURE_DIR/usermanagers" ;;
  cat) is_active "$2" && exit 0 || exit 1 ;;
esac
exit 0
STUB

  # Stub getent passwd: reads $FIXTURE_DIR/passwd, formatted <uid> <name>
  cat >"${BATS_TEST_TMPDIR}/getent" <<'STUB'
#!/usr/bin/env bash
[ "$1" = passwd ] || exit 1
name=$(awk -v u="$2" '$1==u {print $2}' "$FIXTURE_DIR/passwd" 2>/dev/null)
[ -n "$name" ] || exit 2
echo "${name}:x:${2}:${2}::/nonexistent:/usr/sbin/nologin"
STUB

  # Stub free/nproc so the suite runs on any host, not just Linux.
  cat >"${BATS_TEST_TMPDIR}/free" <<'STUB'
#!/usr/bin/env bash
avail=$(cat "$FIXTURE_DIR/mem_available" 2>/dev/null || echo 25000)
echo "               total        used        free      shared  buff/cache   available"
echo "Mem:           31083        5902       19636          32        6033       ${avail}"
STUB
  printf '#!/usr/bin/env bash\necho 20\n' >"${BATS_TEST_TMPDIR}/nproc"

  chmod +x "${BATS_TEST_TMPDIR}"/{loginctl,systemctl,getent,free,nproc}
  export DISPLAY_MODE_FREE="${BATS_TEST_TMPDIR}/free"
  export DISPLAY_MODE_NPROC="${BATS_TEST_TMPDIR}/nproc"
  export DISPLAY_MODE_LOGINCTL="${BATS_TEST_TMPDIR}/loginctl"
  export DISPLAY_MODE_SYSTEMCTL="${BATS_TEST_TMPDIR}/systemctl"
  export DISPLAY_MODE_GETENT="${BATS_TEST_TMPDIR}/getent"
  export DISPLAY_MODE_NVIDIA_SMI="/nonexistent/nvidia-smi"
  export SUDO_UID=1000

  # Default fixture: the real shape measured on tushar-ubuntu-26-desktop.
  cat >"$FIXTURE_DIR/sessions" <<'EOF'
1 1000 user -
2 60578 greeter -
c1 60578 greeter seat0
3 1000 manager -
EOF
  printf 'display-manager.service\nuser@60578.service\nuser@1000.service\n' >"$FIXTURE_DIR/active"
  printf '60578 gdm-greeter\n975 gdm\n1000 tushar\n' >"$FIXTURE_DIR/passwd"
  printf 'user@60578.service loaded active running\nuser@1000.service loaded active running\n' \
    >"$FIXTURE_DIR/usermanagers"

  # shellcheck source=/dev/null
  source "$SCRIPT"
}

# --- greeter uid resolution -------------------------------------------------

@test "resolves the greeter uid from a Class=greeter session, not id -u gdm" {
  run resolve_greeter_uid
  [ "$status" -eq 0 ]
  [ "$output" = "60578" ]
}

@test "deduplicates a greeter holding several sessions" {
  run resolve_greeter_uid
  [ "$(echo "$output" | wc -l | tr -d ' ')" = "1" ]
}

@test "falls back to running user@ units when no greeter session is present" {
  printf '1 1000 user -\n' >"$FIXTURE_DIR/sessions"
  run resolve_greeter_uid
  [ "$status" -eq 0 ]
  [ "$output" = "60578" ]
}

@test "fallback ignores user@ units whose account is not a gdm account" {
  printf '1 1000 user -\n' >"$FIXTURE_DIR/sessions"
  printf '60578 someoneelse\n1000 tushar\n' >"$FIXTURE_DIR/passwd"
  run resolve_greeter_uid
  [ -z "$output" ]
}

# --- the guards that stop this from killing your own session ----------------

@test "rejects an empty greeter uid" {
  run assert_greeter_uid ""
  [ "$status" -ne 0 ]
  [[ "$output" == *"could not resolve a greeter session"* ]]
}

@test "rejects uid 1000" {
  run assert_greeter_uid "1000"
  [ "$status" -ne 0 ]
  [[ "$output" == *"1000, a human account"* ]]
}

@test "rejects the invoking user's uid" {
  SUDO_UID=1234 run assert_greeter_uid "1234"
  [ "$status" -ne 0 ]
  [[ "$output" == *"invoking user"* ]]
}

@test "rejects root" {
  run assert_greeter_uid "0"
  [ "$status" -ne 0 ]
}

@test "rejects a non-numeric uid" {
  run assert_greeter_uid "gdm"
  [ "$status" -ne 0 ]
  [[ "$output" == *"not numeric"* ]]
}

@test "rejects an ambiguous multi-candidate result" {
  run assert_greeter_uid "$(printf '60578\n60579')"
  [ "$status" -ne 0 ]
  [[ "$output" == *"ambiguous"* ]]
}

@test "accepts the real greeter uid" {
  run assert_greeter_uid "60578"
  [ "$status" -eq 0 ]
  [ "$output" = "60578" ]
}

# --- target ordering --------------------------------------------------------

@test "display manager is ordered before the greeter user manager" {
  run target_units
  [ "$status" -eq 0 ]
  [ "$(echo "$output" | head -1)" = "display-manager.service" ]
  [ "$(echo "$output" | tail -1)" = "user@60578.service" ]
}

# --- never stop an inactive unit (the set -e abort) -------------------------

@test "unit_active is false for a unit that is not running" {
  run unit_active "cups.service"
  [ "$status" -ne 0 ]
}

@test "an inactive unit is skipped rather than stopped" {
  printf 'user@60578.service\nuser@1000.service\n' >"$FIXTURE_DIR/active"
  run do_disable "yes"
  [ "$status" -eq 0 ]
  [[ "$output" == *"skip     display-manager.service"* ]]
  ! grep -q 'display-manager.service' "$FIXTURE_DIR/stopped" 2>/dev/null
}

# --- state round-trip -------------------------------------------------------

@test "disable records exactly the units it stopped" {
  run do_disable "yes"
  [ "$status" -eq 0 ]
  grep -qx 'unit=display-manager.service' "$DISPLAY_MODE_STATE"
  grep -qx 'unit=user@60578.service' "$DISPLAY_MODE_STATE"
  ! grep -q 'user@1000.service' "$DISPLAY_MODE_STATE"
}

@test "enable restarts the recorded set in reverse order" {
  do_disable "yes" >/dev/null
  run do_enable
  [ "$status" -eq 0 ]
  [ "$(head -1 "$FIXTURE_DIR/started")" = "user@60578.service" ]
  [ "$(tail -1 "$FIXTURE_DIR/started")" = "display-manager.service" ]
}

@test "enable removes the state file so status reports desktop mode" {
  do_disable "yes" >/dev/null
  do_enable >/dev/null
  [ ! -f "$DISPLAY_MODE_STATE" ]
}

@test "a truncated state file still restores what was recorded" {
  do_disable "yes" >/dev/null
  head -2 "$DISPLAY_MODE_STATE" >"${DISPLAY_MODE_STATE}.trunc"
  mv "${DISPLAY_MODE_STATE}.trunc" "$DISPLAY_MODE_STATE"
  run do_enable
  [ "$status" -eq 0 ]
}

@test "repeat disable is a no-op and does not clobber recorded state" {
  do_disable "yes" >/dev/null
  cp "$DISPLAY_MODE_STATE" "${BATS_TEST_TMPDIR}/first"
  run do_disable "yes"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Already in compute mode"* ]]
  diff -q "${BATS_TEST_TMPDIR}/first" "$DISPLAY_MODE_STATE"
}

@test "enable with no state file is a no-op" {
  run do_enable
  [ "$status" -eq 0 ]
  [[ "$output" == *"nothing recorded to restore"* ]]
}

# --- local session guard ----------------------------------------------------

@test "refuses to stop the desktop when a seated user session exists" {
  printf '1 1000 user seat0\n2 60578 greeter -\n' >"$FIXTURE_DIR/sessions"
  run check_local_session "no"
  [ "$status" -ne 0 ]
  [[ "$output" == *"would be terminated"* ]]
}

@test "the greeter's own seated session does not trip the guard" {
  run check_local_session "no"
  [ "$status" -eq 0 ]
}

@test "--force overrides the local session guard" {
  printf '1 1000 user seat0\n' >"$FIXTURE_DIR/sessions"
  run check_local_session "yes"
  [ "$status" -eq 0 ]
}

# --- GPU preconditions ------------------------------------------------------

@test "gpu preconditions are skipped when nvidia-smi is absent" {
  run check_gpu_preconditions "no"
  [ "$status" -eq 0 ]
}

# Regression: nvidia-persistenced reports `active` on the real host while
# persistence mode is `Disabled`, so checking the unit state alone is a false
# pass. The guard must read persistence_mode itself.
stub_nvidia() {
  cat >"${BATS_TEST_TMPDIR}/nvidia-smi" <<STUB
#!/usr/bin/env bash
case "\$*" in
  *persistence_mode*) echo "$1" ;;
  *compute-apps*)     printf '%s' "$2" ;;
  *memory.used*)      echo 115 ;;
esac
STUB
  chmod +x "${BATS_TEST_TMPDIR}/nvidia-smi"
  # The script resolves NVIDIA_SMI from the env at source time, which already
  # happened in setup(). Override the resolved variable, not just the env var.
  export DISPLAY_MODE_NVIDIA_SMI="${BATS_TEST_TMPDIR}/nvidia-smi"
  NVIDIA_SMI="${BATS_TEST_TMPDIR}/nvidia-smi"
}

@test "refuses when GPU persistence mode is Disabled" {
  stub_nvidia "Disabled" ""
  run check_gpu_preconditions "no"
  [ "$status" -ne 0 ]
  [[ "$output" == *"persistence mode is 'Disabled'"* ]]
  [[ "$output" == *"nvidia-smi -pm 1"* ]]
}

@test "passes when GPU persistence mode is Enabled" {
  stub_nvidia "Enabled" ""
  run check_gpu_preconditions "no"
  [ "$status" -eq 0 ]
}

@test "--force overrides Disabled persistence mode but warns" {
  stub_nvidia "Disabled" ""
  run check_gpu_preconditions "yes"
  [ "$status" -eq 0 ]
  [[ "$output" == *"WARNING"* ]]
}

@test "refuses when a GPU compute process is running" {
  stub_nvidia "Enabled" "1234"
  run check_gpu_preconditions "no"
  [ "$status" -ne 0 ]
  [[ "$output" == *"GPU compute process"* ]]
}

# --- argument handling ------------------------------------------------------

@test "no arguments prints usage and exits 2" {
  run bash "$SCRIPT"
  [ "$status" -eq 2 ]
  [[ "$output" == *"Usage: display-mode"* ]]
}

@test "--help exits 0" {
  run bash "$SCRIPT" --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Nothing is permanent"* ]]
}

@test "an unknown argument is rejected" {
  run bash "$SCRIPT" --wat
  [ "$status" -ne 0 ]
  [[ "$output" == *"unknown argument"* ]]
}

@test "a non-root invocation is refused" {
  [ "$(id -u)" -ne 0 ] || skip "running as root"
  run bash "$SCRIPT" --status
  [ "$status" -ne 0 ]
  [[ "$output" == *"must run as root"* ]]
}
