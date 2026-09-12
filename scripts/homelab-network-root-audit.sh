#!/usr/bin/env bash
# Run on the Ubuntu gateway with sudo. Read-only: no network or file mutation.
set -euo pipefail
[[ $EUID -eq 0 ]] || { printf 'Run with sudo on the Ubuntu gateway.\n' >&2; exit 1; }
[[ $(hostname) == tushar-Studio-1458 ]] || { printf 'Unexpected host; refusing audit.\n' >&2; exit 1; }
for command in dnsmasq nft python3 nmcli; do
  command -v "$command" >/dev/null || { printf 'Missing command: %s\n' "$command" >&2; exit 1; }
done
printf 'Read-only gateway audit: '
date -u +%Y-%m-%dT%H:%M:%SZ
printf '\nDHCP configuration syntax:\n'
dnsmasq --test --conf-file=/dev/null --conf-dir=/etc/NetworkManager/dnsmasq-shared.d
printf '\nConfigured dynamic range:\n'
nmcli -g ipv4.shared-dhcp-range connection show server-link
[[ $(nmcli -g ipv4.shared-dhcp-range connection show server-link) == 10.42.0.10,10.42.0.199 ]]
printf '\nActive lease checks (hostnames and client identifiers omitted):\n'
python3 - <<'PY'
from pathlib import Path
import ipaddress
import time

path = Path('/var/lib/NetworkManager/dnsmasq-enp2s0.leases')
if not path.is_file():
    raise SystemExit('FAIL: expected active DHCP lease file is missing')
expected = {
    '10.42.0.115': '6c:ae:8b:52:ff:5a',
    '10.42.0.220': '02:42:00:00:01:00',
    '10.42.0.222': '02:42:00:00:01:02',
    # Retired identities remain reserved, but are not desired VMs.
    '10.42.0.221': '02:42:00:00:01:01',
    '10.42.0.223': '02:42:00:00:01:03',
}
conflicts = []
active = 0
for line in path.read_text().splitlines():
    parts = line.split()
    if len(parts) < 3:
        continue
    expiry, mac, address = parts[:3]
    if not expiry.isdigit():
        raise SystemExit('FAIL: unexpected DHCP lease record format')
    if int(expiry) != 0 and int(expiry) <= time.time():
        continue
    ip = ipaddress.ip_address(address)
    if ip.version != 4:
        continue
    active += 1
    print(f'Active lease: {address} MAC {mac}')
    expected_mac = expected.get(address)
    if expected_mac and mac.lower() != expected_mac:
        conflicts.append(address + ': reserved address has an unexpected MAC')
    if mac.lower() in expected.values() and expected_mac != mac.lower():
        conflicts.append(address + ': known MAC leased an unexpected address')
    if ip in ipaddress.ip_network('10.42.0.0/24'):
        last = int(address.rsplit('.', 1)[1])
        if last >= 200 and address not in expected:
            conflicts.append(address + ': active lease overlaps excluded address space')
if conflicts:
    raise SystemExit('FAIL: ' + '; '.join(conflicts))
print(f'PASS: {active} active IPv4 leases inspected; no recorded reservation/exclusion conflicts')
print('No guest lease is expected before guest creation; this does not prove unused addresses are free.')
PY
printf '\nActive firewall rules for review (includes NAT and forwarding):\n'
nft --stateless list ruleset
printf '\nPASS: syntax/range/lease checks. Firewall output requires review.\n'
printf 'No configuration changed. Router reservation, reboot persistence, client routing and DR remain separate checks.\n'
