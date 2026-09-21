#!/usr/bin/env bash
# This launches the existing cluster only. Never create a replacement system disk.
set -euo pipefail
umask 077
cd "${PILOT_VM_DIR:-$HOME/talos-wifi-prototype}"
[[ -r /dev/kvm && -w /dev/kvm ]]
[[ -f PROTOTYPE-control-plane.qcow2 && -f pilot-monitoring.qcow2 && -f metal-amd64.iso ]]
ip link show tp103tap >/dev/null
if [[ -f qemu.pid ]] && kill -0 "$(cat qemu.pid)" 2>/dev/null; then
  echo 'VM is already running' >&2; exit 1
fi
qemu-system-x86_64 \
  -name PROTOTYPE-talos-wifi \
  -machine q35,accel=kvm -cpu host -smp 3 -m 6144 \
  -cdrom metal-amd64.iso -boot order=c \
  -netdev tap,id=proto,ifname=tp103tap,script=no,downscript=no \
  -device virtio-net-pci,netdev=proto,mac=52:54:00:77:03:01 \
  -device virtio-rng-pci -display none -serial file:serial.log \
  -monitor unix:monitor.sock,server=on,wait=off \
  -drive file=PROTOTYPE-control-plane.qcow2,format=qcow2,if=none,id=system \
  -device virtio-blk-pci,drive=system,bootindex=1 \
  -drive file=pilot-monitoring.qcow2,format=qcow2,if=none,id=monitoring \
  -device virtio-blk-pci,drive=monitoring,serial=PILOT-MONITORING-01 \
  -device virtio-balloon-pci,id=pilot-balloon,free-page-reporting=on \
  -pidfile qemu.pid -daemonize
