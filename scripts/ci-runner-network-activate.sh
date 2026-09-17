#!/usr/bin/env bash
set -euo pipefail
printf "%s\n" "Retired: laptop DHCP/NAT is no longer used. Run scripts/homelab-network-validate.sh for the direct LAN." >&2
exit 1
