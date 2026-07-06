#!/usr/bin/env bash

set -euo pipefail

network_service="${1:-Wi-Fi}"
pihole_address="${2:-10.0.0.232}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script only supports macOS." >&2
  exit 1
fi

if ! networksetup -listallnetworkservices | tail -n +2 | grep -Fxq "${network_service}"; then
  echo "Unknown macOS network service: ${network_service}" >&2
  exit 1
fi

echo "Setting ${network_service} DNS to Pi-hole at ${pihole_address}..."
sudo networksetup -setdnsservers "${network_service}" "${pihole_address}"
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder

echo "Configured DNS servers:"
networksetup -getdnsservers "${network_service}"

