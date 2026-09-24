#!/usr/bin/env bash
# Root-owned bounded dispatcher. No caller-controlled commands or paths.
set -euo pipefail
[[ $EUID -eq 0 && $# -eq 1 ]]
base=/usr/local/lib/main-control-plane
state=/var/lib/main-control-plane
pve() { runuser -u tushar -- ssh -o BatchMode=yes -o ConnectTimeout=10 -i /home/tushar/.ssh/main-proxmox root@10.0.0.224 "$1"; }
case "$1" in
  test-up|test-verify)
    echo 'Legacy probe address 10.0.0.226 now belongs to ubuntu-gpu-01; allocate and review new probe addresses first.' >&2
    exit 1
    ;;
  test-down)
    for pid in $(ip netns pids maincp-test); do kill "$pid"; done
    ip netns del maincp-test
    "$base/network.py" down
    ;;
  activate)
    [[ -f "$state/network-proven" && ! -f "$state/source-fenced" ]]
    [[ $(pve 'qm status 100') == 'status: stopped' ]]
    pve 'qm config 100' | grep -Fx 'onboot: 0'
    pve 'qm config 100' | grep -Fx 'protection: 1'
    [[ -f "$state/vm/copy.json" ]]
    python3 "$base/verify-copy.py"
    cp "$state/vm/copy.json" "$state/copy-verified"
    date -u +%FT%TZ > "$state/source-fenced"
    systemctl start main-control-plane.service
    ;;
  stop)
    systemctl stop main-control-plane.service
    if fuser "$state/vm/system.qcow2"; then
      echo 'Guest did not stop; preserve network and inspect Talos/QMP.' >&2; exit 1
    fi
    systemctl stop main-control-plane-network.service
    ;;
  restart)
    [[ -f "$state/source-fenced" && -f "$state/copy-verified" ]]
    systemctl restart main-control-plane.service
    ;;
  accept)
    [[ -f "$state/source-fenced" && -f "$state/copy-verified" ]]
    systemctl is-active --quiet main-control-plane.service
    python3 -c 'import json; d=json.load(open("/home/tushar/.local/share/main-control-plane/acceptance.json")); assert d["passed"] is True and d["component"] == "control-plane"'
    systemctl enable main-control-plane.service
    ;;
  *) echo 'Expected test-up, test-verify, test-down, activate, stop, restart, or accept' >&2; exit 2 ;;
esac
