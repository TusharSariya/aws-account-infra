#!/usr/bin/env bash
# Run over verified root SSH on pve. Idempotent, no VM or disk mutation.
set -euo pipefail
[[ $(id -u) == 0 && $(hostname) == pve ]]
[[ $(cat /sys/module/kvm_intel/parameters/nested) == Y ]]
# New scoped role avoids changing permissions on the existing ISO-audit role.
pveum role list --output-format json | python3 -c '
import json,sys
r={x["roleid"]:set(x.get("privs", "").replace(",", " ").split()) for x in json.load(sys.stdin)}
expected={"Datastore.Audit", "Datastore.AllocateTemplate"}
if "HomelabCIImage" in r and r["HomelabCIImage"] != expected:
 raise SystemExit("Unexpected existing CI image role")
'
if ! pveum role list --output-format json | python3 -c 'import json,sys;sys.exit(not any(v["roleid"]=="HomelabCIImage" for v in json.load(sys.stdin)))'; then
  pveum role add HomelabCIImage --privs 'Datastore.Audit Datastore.AllocateTemplate'
fi
for identity in homelab-tofu@pve homelab-tofu-plan@pve; do
  role=HomelabTofuVM
  [[ $identity != homelab-tofu-plan@pve ]] || role=HomelabTofuPlanVM
  pveum acl modify /vms/103 --users "$identity" --roles "$role" --propagate 0
  pveum acl modify /vms/103 --tokens "$identity!provider" --roles "$role" --propagate 0
done
pveum acl modify /storage/local --users homelab-tofu@pve --roles HomelabCIImage --propagate 0
pveum acl modify /storage/local --tokens 'homelab-tofu@pve!provider' --roles HomelabCIImage --propagate 0
# Cloud-init is needed only for the Ubuntu manager, never the Talos guests.
if ! pveum role list --output-format json | python3 -c 'import json,sys;r={v["roleid"]:set(v.get("privs", "").replace(",", " ").split()) for v in json.load(sys.stdin)};sys.exit(0 if r.get("HomelabCICloudInit")=={"VM.Config.Cloudinit"} else 1 if "HomelabCICloudInit" not in r else 2)'; then
  pveum role add HomelabCICloudInit --privs VM.Config.Cloudinit
fi
pveum acl modify /vms/103 --users homelab-tofu@pve --roles HomelabCICloudInit --propagate 0
pveum acl modify /vms/103 --tokens 'homelab-tofu@pve!provider' --roles HomelabCICloudInit --propagate 0
printf 'PASS: CI image and VM 103 permissions installed; no VM changed\n'
