#!/usr/bin/env bash
# Temporary, device-scoped KVM access. Run from an interactive SSH shell.
set -euo pipefail
[[ $EUID == 0 && ${SUDO_USER:-} == tushar && $(hostname) == tushar-Studio-1458 ]]
[[ $# == 0 ]]
[[ $(systemctl get-default) == graphical.target ]]
ip -4 addr show tp103br | grep -q 'inet 10.0.2.2/24'
systemctl stop display-manager.service
# User ACLs on uaccess devices can be removed by logind when seats change.
# Use the existing private primary group, plus a runtime-only rule for device recreation.
[[ $(getent group tushar) == tushar:x:1000: ]]
[[ $(id -g tushar) == 1000 ]]
install -d -m 755 /run/udev/rules.d
cat > /run/udev/rules.d/99-pilot-kvm.rules <<'RULE'
SUBSYSTEM=="misc", KERNEL=="kvm", RUN+="/usr/bin/setfacl -m g:tushar:rw /dev/kvm"
RULE
chmod 644 /run/udev/rules.d/99-pilot-kvm.rules
udevadm control --reload-rules
setfacl -m g:tushar:rw /dev/kvm
# Never execute a user-writable script as root or alter the graphical boot default.
echo 'Desktop stopped temporarily; KVM access restored. Run migrate.py resize as tushar.'
