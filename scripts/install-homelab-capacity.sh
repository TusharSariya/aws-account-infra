#!/usr/bin/env bash
# Idempotent recipe. Run on Proxmox with an audited checkout and separately
# provisioned certificate directory. Does not issue or print credentials.
set -euo pipefail
[[ $(id -u) == 0 && $(uname -s) == Linux ]]
[[ $# == 1 ]] || { echo 'Usage: install-homelab-capacity.sh /protected/credential-directory' >&2; exit 2; }
source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
credential_dir=$1
for file in config.json server.crt server.key client-ca.crt; do
  [[ -f "$credential_dir/$file" && ! -L "$credential_dir/$file" ]]
done
python3 - "$credential_dir/config.json" <<'PY'
import ipaddress, json, re, sys
config = json.load(open(sys.argv[1]))
assert set(config) == {'bind', 'pool'}
assert ipaddress.ip_address(config['bind']) in ipaddress.ip_network('100.64.0.0/10')
assert re.fullmatch(r'[A-Za-z0-9_+.-]+/[A-Za-z0-9_+.-]+', config['pool'])
PY
# Proxmox already supplies LVM and Python; no unpinned package installation.
[[ -x /usr/sbin/lvs && -x /usr/bin/python3 ]]
getent group homelab-capacity >/dev/null || groupadd --system homelab-capacity
id homelab-capacity >/dev/null 2>&1 || useradd --system --gid homelab-capacity --no-create-home --shell /usr/sbin/nologin homelab-capacity
install -d -o root -g root -m 0755 /usr/local/lib/homelab-capacity
install -d -o root -g homelab-capacity -m 0750 /etc/homelab-capacity
install -o root -g root -m 0644 "$source_root/apps/platform/storage/physical.py" "$source_root/apps/platform/storage/physical_server.py" /usr/local/lib/homelab-capacity/
for file in config.json server.crt server.key client-ca.crt; do
  install -o root -g homelab-capacity -m 0640 "$credential_dir/$file" "/etc/homelab-capacity/$file"
done
install -o root -g root -m 0644 "$source_root"/config/environments/proxmox/homelab/capacity/*.service "$source_root"/config/environments/proxmox/homelab/capacity/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl start homelab-capacity-sample.service
systemctl enable --now homelab-capacity-sample.timer
systemctl enable homelab-capacity-exporter.service
systemctl restart homelab-capacity-exporter.service
systemctl is-active --quiet homelab-capacity-sample.timer homelab-capacity-exporter.service
