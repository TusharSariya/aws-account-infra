#!/usr/bin/env bash
# Remove only dedicated CI ACL entries after the identified VM is absent.
set -euo pipefail
[[ $(id -u) == 0 && $(hostname) == pve ]]
pvesh get /nodes/pve/qemu --output-format json | python3 -c 'import json,sys; assert not any(int(x["vmid"]) == 103 for x in json.load(sys.stdin)), "VM 103 must be retired first"'
for identity in homelab-tofu@pve homelab-tofu-plan@pve; do
  role=HomelabTofuVM
  [[ $identity != homelab-tofu-plan@pve ]] || role=HomelabTofuPlanVM
  pveum acl delete /vms/103 --users "$identity" --roles "$role"
  pveum acl delete /vms/103 --tokens "$identity!provider" --roles "$role"
done
pveum acl delete /storage/local --users homelab-tofu@pve --roles HomelabCIImage
pveum acl delete /storage/local --tokens 'homelab-tofu@pve!provider' --roles HomelabCIImage
pveum acl delete /vms/103 --users homelab-tofu@pve --roles HomelabCICloudInit
pveum acl delete /vms/103 --tokens 'homelab-tofu@pve!provider' --roles HomelabCICloudInit
# Shared provider identities and the GitHub App/key are deliberately retained.
printf 'Dedicated CI ACL entries removed; shared identities retained.\n'
