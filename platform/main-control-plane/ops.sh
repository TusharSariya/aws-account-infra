#!/usr/bin/env bash
# Root-owned bounded dispatcher. No caller-controlled commands or paths.
set -euo pipefail
[[ $EUID -eq 0 && $# -eq 1 ]]
base=/usr/local/lib/main-control-plane
state=/var/lib/main-control-plane
pve() { runuser -u tushar -- ssh -o BatchMode=yes -o ConnectTimeout=10 -i /home/tushar/.ssh/main-proxmox root@10.0.0.224 "$1"; }
case "$1" in
  test-up)
    [[ ! -f "$state/source-fenced" && ! -f "$state/network-proven" ]]
    # Addresses are outside DHCP (.220) and MetalLB (.232+) per the inventory.
    for address in 10.0.0.226 10.0.0.227; do
      arping -D -I wlp5s0b1 -c 3 "$address"
    done
    "$base/network.py" test-up --test-addresses 10.0.0.226 10.0.0.227
    ip netns add maincp-test
    ip link add mcptest-host type veth peer name mcptest-guest
    ip link set mcptest-host master maincpbr
    ip link set mcptest-host up
    ip link set mcptest-guest netns maincp-test
    ip -n maincp-test link set lo up
    ip -n maincp-test link set mcptest-guest up
    ip -n maincp-test addr add 10.0.0.226/24 dev mcptest-guest
    ip -n maincp-test addr add 10.0.0.227/32 dev mcptest-guest
    ip -n maincp-test route add default via 10.0.0.1
    ip netns exec maincp-test python3 "$base/probe-server.py" > "$state/probe.log" 2>&1 &
    ;;
  test-verify)
    for address in 10.0.0.1 10.0.0.224 10.0.0.222; do
      ip netns exec maincp-test ping -c 3 -W 3 "$address"
    done
    for address in 10.0.0.226 10.0.0.227; do
      pve "curl --fail --max-time 10 http://$address:16443/" | grep -Fx main-control-plane-network-probe
    done
    date -u +%FT%TZ > "$state/network-proven"
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
