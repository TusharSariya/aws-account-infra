#!/usr/bin/env bash
# Run as root on pve. Advertises the approved IPv4 route; tailnet approval is separate.
set -euo pipefail
[[ $EUID -eq 0 && $(hostname) == pve ]] || { echo 'Run as root on pve.' >&2; exit 1; }
ip -4 address show vmbr0 | grep -q 'inet 10.42.0.115/24'
command -v tailscale >/dev/null
# Refuse to replace unrelated route advertisements or a different SNAT policy.
tailscale debug prefs | python3 -c 'import json,sys; p=json.load(sys.stdin); assert p.get("AdvertiseRoutes") in (None, [], ["10.42.0.0/24"]), "Unexpected existing routes"; assert not p.get("NoSNAT"), "Existing SNAT policy differs"'
target=/etc/sysctl.d/99-homelab-tailscale.conf
if [[ -e $target ]]; then
  grep -Fxq 'net.ipv4.ip_forward = 1' "$target" || { echo 'Existing sysctl file differs; inspect first.' >&2; exit 1; }
else
  printf '%s\n' '# IPv4 subnet routing through pve; managed by homelab-tailscale-subnet.sh.' 'net.ipv4.ip_forward = 1' > "$target"
  chmod 644 "$target"
fi
sysctl -p "$target"
tailscale set --advertise-routes=10.42.0.0/24
tailscale debug prefs | python3 -c 'import json,sys; p=json.load(sys.stdin); print("Advertised routes:",p.get("AdvertiseRoutes")); print("Subnet SNAT enabled:",not p.get("NoSNAT")); assert p.get("AdvertiseRoutes")==["10.42.0.0/24"]'
echo 'Host configured. Approve the route and review access policy in the Tailscale admin console.'
