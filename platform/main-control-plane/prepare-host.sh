#!/usr/bin/env bash
# Root preparation only. Does not stop pilot/main or advertise cluster addresses.
set -euo pipefail
[[ $EUID -eq 0 ]]
base=$(cd -- "$(dirname -- "$0")" && pwd)
if ! command -v arping >/dev/null; then apt-get update; apt-get install -y iputils-arping; fi
for binary in qemu-system-x86_64 qemu-img nft ip python3 arping fuser; do command -v "$binary" >/dev/null; done
[[ -d /sys/class/net/wlp5s0b1/wireless ]]
getent passwd tushar >/dev/null
getent group kvm >/dev/null
install -d -m 0755 /usr/local/lib/main-control-plane
install -m 0755 "$base/launch.sh" "$base/stop.py" "$base/network.py" "$base/ops.sh" "$base/verify-copy.py" "$base/probe-server.py" /usr/local/lib/main-control-plane/
install -m 0644 "$base"/systemd/*.service /etc/systemd/system/
install -d -m 0755 /var/lib/main-control-plane
install -d -m 0700 -o tushar -g tushar /var/lib/main-control-plane/vm
usermod -aG kvm tushar
# Persistent device permissions, scoped to the KVM group.
printf '%s\n' 'SUBSYSTEM=="misc", KERNEL=="kvm", GROUP="kvm", MODE="0660"' > /etc/udev/rules.d/70-main-control-plane-kvm.rules
udevadm control --reload-rules
udevadm trigger --subsystem-match=misc --sysname-match=kvm
install -d /etc/systemd/logind.conf.d
printf '%s\n' '[Login]' 'HandleLidSwitch=ignore' 'HandleLidSwitchExternalPower=ignore' 'HandleLidSwitchDocked=ignore' > /etc/systemd/logind.conf.d/70-main-control-plane.conf
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
install -m 0755 "$base/90-main-control-plane" /etc/NetworkManager/dispatcher.d/90-main-control-plane
systemctl daemon-reload
# Deliberately do not restart logind or alter graphical.target.
[[ $(systemctl get-default) == graphical.target ]]
printf '%s\n' 'Host prepared. Main services remain disabled pending networking and offline-copy verification.'
# Permit only the reviewed root-owned dispatcher, never arbitrary root commands.
printf '%s\n' 'tushar ALL=(root) NOPASSWD: /usr/local/lib/main-control-plane/ops.sh test-up, /usr/local/lib/main-control-plane/ops.sh test-verify, /usr/local/lib/main-control-plane/ops.sh test-down, /usr/local/lib/main-control-plane/ops.sh activate, /usr/local/lib/main-control-plane/ops.sh stop, /usr/local/lib/main-control-plane/ops.sh restart, /usr/local/lib/main-control-plane/ops.sh accept' > /etc/sudoers.d/main-control-plane
chmod 0440 /etc/sudoers.d/main-control-plane
visudo -cf /etc/sudoers.d/main-control-plane
