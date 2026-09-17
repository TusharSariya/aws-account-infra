#!/usr/bin/env bash
# Read-only Proxmox bridge, route and forwarding audit.
set -euo pipefail
[[ $EUID -eq 0 && $(hostname) == pve ]] || { echo 'Run as root on pve.' >&2; exit 1; }
ip -4 address show vmbr0 | grep -F 'inet 10.0.0.92/24'
ip -4 route show default | grep -F 'default via 10.0.0.1 dev vmbr0'
ip -s link show vmbr0
bridge link show
sysctl net.ipv4.ip_forward
nft --stateless list ruleset
printf 'Read-only audit complete; review firewall output. LAN router DHCP is managed separately.\n'
