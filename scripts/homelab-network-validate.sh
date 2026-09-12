#!/usr/bin/env bash
# Read-only checks for the laptop-connected homelab. Run from the admin Mac.
# Requires existing laptop-dell-studio and server-10-42 SSH aliases.
set -euo pipefail

ssh_options=(-T -o BatchMode=yes -o ConnectTimeout=8)

ssh "${ssh_options[@]}" laptop-dell-studio 'bash -se' <<'LAPTOP'
set -euo pipefail
[[ $(hostname) == tushar-Studio-1458 ]]
[[ $(nmcli -g connection.interface-name connection show server-link) == enp2s0 ]]
[[ $(nmcli -g connection.autoconnect connection show server-link) == yes ]]
[[ $(nmcli -g ipv4.method connection show server-link) == shared ]]
[[ $(nmcli -g ipv4.addresses connection show server-link) == 10.42.0.1/24 ]]
[[ $(nmcli -g ipv4.shared-dhcp-range connection show server-link) == 10.42.0.10,10.42.0.199 ]]
ip -4 address show enp2s0 | grep -F 'inet 10.42.0.1/24'
ip -4 address show wlp5s0b1 | grep -F 'inet 10.0.0.181/24'
ip -4 route show default | grep -F 'default via 10.0.0.1 dev wlp5s0b1'
[[ $(sysctl -n net.ipv4.conf.enp2s0.forwarding) == 1 ]]
[[ $(sysctl -n net.ipv4.conf.wlp5s0b1.forwarding) == 1 ]]
pgrep -a -x dnsmasq | grep -F -- '--listen-address=10.42.0.1' |
  grep -F -- '--dhcp-range=10.42.0.10,10.42.0.199,3600' |
  grep -F -- '--conf-dir=/etc/NetworkManager/dnsmasq-shared.d'
grep -Fx 'dhcp-host=6c:ae:8b:52:ff:5a,10.42.0.115,pve,infinite' \
  /etc/NetworkManager/dnsmasq-shared.d/pve-reservation.conf
for entry in \
  '02:42:00:00:01:00,10.42.0.220,talos-cp-01' \
  '02:42:00:00:01:02,10.42.0.222,talos-worker-01'; do
  grep -Fx "dhcp-host=$entry,infinite" /etc/NetworkManager/dnsmasq-shared.d/homelab-guests.conf
done
systemctl is-active --quiet NetworkManager
systemctl is-active --quiet ssh
ping -c 2 -W 3 10.42.0.115
printf 'PASS: saved/active laptop network, forwarding, reservation files and Proxmox reachability\n'
LAPTOP

ssh "${ssh_options[@]}" server-10-42 'bash -se' <<'PROXMOX'
set -euo pipefail
[[ $(hostname) == pve ]]
ip -4 address show vmbr0 | grep -F 'inet 10.42.0.115/24'
ip -4 route show default | grep -F 'default via 10.42.0.1 dev vmbr0'
grep -Fx 'nameserver 10.42.0.1' /etc/resolv.conf
ping -c 2 -W 3 10.42.0.1
getent ahostsv4 deb.debian.org
curl --fail --silent --show-error --head --max-time 15 https://deb.debian.org/debian/ >/dev/null
printf 'PASS: Proxmox SSH via laptop, gateway, DNS and outbound HTTPS\n'
PROXMOX

printf '%s\n' \
  'PASS: current-network checks. No configuration was changed.' \
  'This script alone does not establish fresh guest leases, root-only firewall/lease state,' \
  'reboot history, backup recovery, router reservations or GPU-worker routing.' \
  'See network-plan.md and implementation-log.md for separately recorded verification.'
