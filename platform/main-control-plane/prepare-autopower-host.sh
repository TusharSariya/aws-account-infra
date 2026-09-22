#!/usr/bin/env bash
# Add dedicated DNS storage without touching the running guest or its disks.
set -euo pipefail
[[ $EUID -eq 0 ]]
base=$(cd -- "$(dirname -- "$0")" && pwd)
state=/var/lib/main-control-plane
[[ -f "$state/source-fenced" && -f "$state/copy-verified" ]]
command -v qemu-img >/dev/null
bash -n "$base/launch.sh"
# Verify existing files instead of replacing them on repeat invocations.
if [[ ! -e "$state/vm/dns.qcow2" ]]; then
  available=$(df --output=avail -B1 "$state/vm" | tail -1)
  [[ "$available" -ge 8589934592 ]]
  temporary=$(mktemp "$state/vm/.dns-XXXXXXXX.qcow2")
  trap 'rm -f "$temporary"' EXIT
  qemu-img create -f qcow2 "$temporary" 4G
  chown tushar:tushar "$temporary"
  chmod 0600 "$temporary"
  mv -n "$temporary" "$state/vm/dns.qcow2"
fi
qemu-img info --output=json "$state/vm/dns.qcow2" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["format"] == "qcow2" and d["virtual-size"] == 4*1024**3 and not d.get("backing-filename")'
# Preserve the previous root-owned launch configuration for operator recovery.
if [[ ! -e "$state/launch-before-autopower.sh" ]]; then
  install -m 0700 /usr/local/lib/main-control-plane/launch.sh "$state/launch-before-autopower.sh"
fi
install -m 0755 "$base/launch.sh" /usr/local/lib/main-control-plane/launch.sh
cmp "$base/launch.sh" /usr/local/lib/main-control-plane/launch.sh
printf '%s\n' 'Prepared. Running services unchanged; no automatic power actions enabled.'
