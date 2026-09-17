#!/usr/bin/env bash
# Read-only direct-LAN checks from the administration Mac.
set -euo pipefail
ssh -T -o BatchMode=yes -o ConnectTimeout=8 -o ProxyJump=none -o ProxyCommand=none root@10.0.0.92 'bash -se' <<'PROXMOX'
set -euo pipefail
[[ $(hostname) == pve ]]
ip -4 address show vmbr0 | grep -F 'inet 10.0.0.92/24'
ip -4 route show default | grep -F 'default via 10.0.0.1 dev vmbr0'
for address in 10.0.0.1 10.0.0.220 10.0.0.222 10.0.0.231; do
  ping -c 1 -W 3 "$address" >/dev/null
done
getent ahostsv4 deb.debian.org >/dev/null
curl --fail --silent --show-error --head --max-time 15 https://deb.debian.org/debian/ >/dev/null
printf 'PASS: direct Proxmox SSH, LAN gateway, Talos nodes, API VIP, DNS and outbound HTTPS\n'
PROXMOX
printf 'Read-only checks complete. DHCP reservations, off-LAN Tailscale access and recovery require separate evidence.\n'
