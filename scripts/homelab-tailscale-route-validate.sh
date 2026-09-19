#!/usr/bin/env bash
# Read-only route advertisement and authenticated remote-host check.
set -euo pipefail
tailscale status --json | python3 -c '
import json,sys
s=json.load(sys.stdin)
p=[p for p in (s.get("Peer") or {}).values() if p.get("HostName")=="pve"]
assert len(p)==1, "Expected exactly one pve peer"
expected={"10.0.0.224/32", "10.0.0.221/32", "10.0.0.222/32", "10.0.0.231/32"}
assert expected.issubset(set(p[0].get("AllowedIPs",[]))), "Host routes not received from pve"
print("PASS: pve advertises the approved LAN host routes")'
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=8 \
  -o ProxyCommand=none -o ProxyJump=none -o HostKeyAlias=10.0.0.224 root@100.101.182.9 \
  'test "$(hostname)" = pve && ping -c 1 -W 3 10.0.0.231 >/dev/null'
printf 'PASS: authenticated Tailscale host access and host-to-VIP reachability. Test subnet forwarding from an off-LAN client separately.\n'
