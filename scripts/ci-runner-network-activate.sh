#!/usr/bin/env bash
# Activate the reviewed CI reservation on the existing NetworkManager router.
set -euo pipefail
[[ $(id -u) == 0 ]]
[[ $(nmcli -g ipv4.method connection show server-link) == shared ]]
[[ $(nmcli -g GENERAL.DEVICES connection show server-link) == enp2s0 ]]
[[ $(nmcli -g ipv4.addresses connection show server-link) == 10.42.0.1/24 ]]
[[ $(nmcli -g ipv4.shared-dhcp-range connection show server-link) == 10.42.0.10,10.42.0.199 ]]
grep -Fxq 'dhcp-host=02:42:00:00:01:05,10.42.0.225,ci-runner-01,infinite' /etc/NetworkManager/dnsmasq-shared.d/ci-runner.conf
dnsmasq --test --conf-file=/dev/null --conf-dir=/etc/NetworkManager/dnsmasq-shared.d
# This is the same Ethernet activation used by homelab-network-wizard.sh.
# SSH arrives over Wi-Fi; leave that connection untouched.
nmcli connection up server-link ifname enp2s0
pgrep -a -x dnsmasq | grep -F -- '--listen-address=10.42.0.1' | grep -F -- '--conf-dir=/etc/NetworkManager/dnsmasq-shared.d'
ping -c 3 -W 3 10.42.0.115
printf 'PASS: CI DHCP reservation activated; Proxmox LAN connectivity verified\n'
