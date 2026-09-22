#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /var/lib/main-control-plane/vm
[[ -r /dev/kvm && -w /dev/kvm ]]
[[ -f /var/lib/main-control-plane/source-fenced ]]
# Receipt is created only after test networking, source shutdown and offline copy.
[[ -f /var/lib/main-control-plane/copy-verified ]]
[[ -f system.qcow2 && -f OVMF_CODE.fd && -f OVMF_VARS.fd ]]
ip link show maincptap >/dev/null
exec flock -n vm.lock qemu-system-x86_64 \
  -name talos-cp-01 -machine q35,accel=kvm,smm=on -cpu host -smp 2 -m 4096 \
  -uuid 46a49cd4-7692-4ed9-b00f-4e791de782b3 \
  -device vmgenid,guid=a04f7689-48c8-45fb-b5b6-adc7d16ee5dc \
  -drive if=pflash,format=raw,unit=0,readonly=on,file=OVMF_CODE.fd \
  -drive if=pflash,format=raw,unit=1,file=OVMF_VARS.fd \
  -global driver=cfi.pflash01,property=secure,value=on \
  -device virtio-scsi-pci,id=scsihw0 \
  -drive file=system.qcow2,format=qcow2,if=none,id=system,cache=none,discard=ignore \
  -device scsi-hd,bus=scsihw0.0,channel=0,scsi-id=0,lun=0,drive=system,bootindex=1 \
  -netdev tap,id=main,ifname=maincptap,script=no,downscript=no \
  -device virtio-net-pci,netdev=main,mac=02:42:00:00:01:00 \
  -chardev socket,path=qga.sock,server=on,wait=off,id=qga0 \
  -device virtio-serial,id=qga0 \
  -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0 \
  -device virtio-rng-pci -display none -serial file:serial.log \
  -qmp unix:qmp.sock,server=on,wait=off
