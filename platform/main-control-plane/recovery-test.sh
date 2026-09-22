#!/usr/bin/env bash
# One operator-started recovery test. No recurring timer or power automation.
set -euo pipefail
[[ $EUID -eq 0 ]]
state=/home/tushar/.local/share/main-control-plane
runuser -u tushar -- test -f "$state/both-hosts-off.json"
python3 -c 'import json; d=json.load(open("/home/tushar/.local/share/main-control-plane/both-hosts-off.json")); assert d["passed"] is True'
if systemctl is-enabled --quiet prototype103-vm.service ||
   systemctl is-enabled --quiet prototype103-network.service ||
   systemctl is-active --quiet prototype103-vm.service; then
  echo "Retire pilot startup units before this test" >&2
  exit 1
fi
systemctl is-enabled --quiet main-control-plane.service
systemctl is-active --quiet main-control-plane.service
for address in 10.0.0.67 10.0.0.98; do
  runuser -u tushar -- ssh -o IdentityAgent=none -o BatchMode=yes -o ConnectTimeout=10 -i /home/tushar/.ssh/main-imm "USERID@$address" 'power state' | grep -F 'power off'
done
nmcli device disconnect wlp5s0b1
sleep 3
connected=false
for _attempt in 1 2 3; do
  if nmcli --wait 40 device connect wlp5s0b1; then connected=true; break; fi
  sleep 5
done
[[ "$connected" == true ]]
# NetworkManager's installed dispatcher restores only this VM's routes/proxies.
for _attempt in 1 2 3 4 5 6; do
  if runuser -u tushar -- python3 /home/tushar/main-control-plane/verify-independence.py check \
    --output "$state/wifi-reconnect-acceptance.json"; then
    sync
    systemctl reboot
    exit 0
  fi
  sleep 10
done
echo 'Wi-Fi reconnected but cluster check failed; reboot withheld. Inspect journal.' >&2
exit 1
