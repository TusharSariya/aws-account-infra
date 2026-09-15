#!/usr/bin/env bash
# Run on pve before planning retirement. No force shutdown or shared VM mutation.
set -euo pipefail
[[ $(id -u) == 0 && $(hostname) == pve ]]
pvesh get /nodes/pve/qemu/103/config --output-format json | python3 -c '
import json,sys
v=json.load(sys.stdin)
assert v["name"] == "ci-runner-01" and int(v["cores"]) == 4 and int(v["memory"]) == 16384, "Unexpected VM 103 identity/capacity"
assert "02:42:00:00:01:05" in v["net0"].lower(), "Unexpected VM 103 MAC"
assert v["scsi0"].startswith("local-lvm:vm-103-disk-") and "size=100G" in v["scsi0"].split(","), "Unexpected CI disk"
'
qm shutdown 103 --timeout 180
pvesh get /nodes/pve/qemu/103/status/current --output-format json | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"] == "stopped", "Graceful shutdown not observed"'
qm set 103 --onboot 0
printf 'Identified CI VM stopped and autostart disabled; ready for guarded retirement plan.\n'
