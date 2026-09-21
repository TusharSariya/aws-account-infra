#!/usr/bin/env bash
# Destination-only, temporary network. Never run while the source copy is online.
set -euo pipefail
umask 077
[[ $EUID == 0 && $# == 3 ]]
user=$1
uplink=$2
address=$3
[[ $user =~ ^[a-z_][a-z0-9_-]*$ && $uplink =~ ^[a-zA-Z0-9_.:-]+$ && $address =~ ^[0-9.]+$ ]]
id "$user" >/dev/null
# Seat changes can remove a named user ACL. Require a private primary group.
kvm_group=$(id -gn "$user")
kvm_gid=$(id -g "$user")
[[ $kvm_group =~ ^[a-z_][a-z0-9_-]*$ ]]
[[ $(getent passwd | awk -F: -v gid="$kvm_gid" '$4 == gid {print $1}') == "$user" ]]
group_members=$(getent group "$kvm_group" | cut -d: -f4)
[[ -z $group_members || $group_members == "$user" ]]
ip -4 addr show dev "$uplink" | grep -F "inet $address/" >/dev/null
[[ -z $(ip -4 route show 10.0.2.0/24) ]]
if ip link show tp103br >/dev/null 2>&1; then echo "Bridge already exists" >&2; exit 1; fi
if ip link show tp103tap >/dev/null 2>&1; then echo "TAP already exists" >&2; exit 1; fi
if nft list table inet pilot_portable >/dev/null 2>&1; then echo "Forward table already exists" >&2; exit 1; fi
if nft list table ip pilot_portable_nat >/dev/null 2>&1; then echo "NAT table already exists" >&2; exit 1; fi
[[ ! -e /run/udev/rules.d/99-pilot-kvm.rules ]]
state=/run/pilot-portable
[[ ! -e $state ]]
install -d -m 700 "$state"
sysctl -n net.ipv4.ip_forward > "$state/original-forwarding"
cat > "$state/rules.nft" <<EOF
table inet pilot_portable {
 chain forward {
  type filter hook forward priority -10; policy accept;
  iifname "tp103br" oifname "$uplink" ip saddr 10.0.2.15 accept
  iifname "$uplink" oifname "tp103br" ip daddr 10.0.2.15 ct state established,related accept
  iifname "$uplink" oifname "tp103br" ip daddr 10.0.2.15 ip saddr 10.0.0.0/24 accept
  iifname "tp103br" drop
  oifname "tp103br" drop
 }
}
table ip pilot_portable_nat {
 chain postrouting {
  type nat hook postrouting priority srcnat; policy accept;
  ip saddr 10.0.2.15 ip daddr != 10.0.0.0/24 oifname "$uplink" masquerade
 }
}
EOF
nft -c -f "$state/rules.nft"
cat > "$state/dnsmasq.conf" <<EOF
interface=tp103br
bind-interfaces
listen-address=10.0.2.2
no-resolv
no-hosts
server=1.1.1.1
server=9.9.9.9
dhcp-range=10.0.2.15,10.0.2.15,255.255.255.0,1h
dhcp-host=52:54:00:77:03:01,10.0.2.15
dhcp-option=option:router,10.0.2.2
dhcp-option=option:dns-server,10.0.2.2
pid-file=$state/dnsmasq.pid
dhcp-leasefile=$state/dnsmasq.leases
EOF
dnsmasq --test --conf-file="$state/dnsmasq.conf"
ip link add tp103br type bridge
ip addr add 10.0.2.2/24 dev tp103br
ip link set tp103br up
ip tuntap add dev tp103tap mode tap user "$user"
ip link set tp103tap master tp103br
ip link set tp103tap up
nft -f "$state/rules.nft"
sysctl -w net.ipv4.ip_forward=1
dnsmasq --conf-file="$state/dnsmasq.conf"
install -d -m 755 /run/udev/rules.d
cat > /run/udev/rules.d/99-pilot-kvm.rules <<EOF
SUBSYSTEM=="misc", KERNEL=="kvm", RUN+="/usr/bin/setfacl -m g:$kvm_group:rw /dev/kvm"
EOF
chmod 644 /run/udev/rules.d/99-pilot-kvm.rules
udevadm control --reload-rules
setfacl -m "g:$kvm_group:rw" /dev/kvm
