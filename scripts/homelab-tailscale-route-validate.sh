#!/usr/bin/env bash
# Read-only forwarding check from the existing administration Mac.
# The laptop host key must already be trusted under 10.0.0.181.
set -euo pipefail
tailscale status --json | python3 -c '
import json,sys
s=json.load(sys.stdin)
p=[p for p in (s.get("Peer") or {}).values() if p.get("HostName")=="pve"]
assert len(p)==1, "Expected exactly one pve peer"
assert "10.42.0.0/24" in p[0].get("AllowedIPs",[]), "Subnet not received from pve"
print("PASS: pve advertises an approved subnet to this client")'
route -n get 10.42.0.1 | grep -E 'interface: utun[0-9]+'
ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes \
  -o HostKeyAlias=10.0.0.181 -o ConnectTimeout=8 \
  -o ProxyCommand=none -o ProxyJump=none \
  -i "$HOME/.ssh/id_ed25519" tushar@10.42.0.1 'bash -se' <<'REMOTE'
[[ $(hostname) == tushar-Studio-1458 ]]
read -r source_ip source_port destination_ip destination_port <<< "$SSH_CONNECTION"
[[ $source_ip == 10.42.0.115 && $destination_ip == 10.42.0.1 && $destination_port == 22 ]]
printf 'PASS: authenticated SSH through pve to laptop Ethernet; expected subnet SNAT confirmed\n'
REMOTE
printf 'Not tested by this check: unauthorized-client denial, guest endpoints, external GPU networking or off-home routing.\n'
