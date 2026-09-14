#!/usr/bin/env bash
# One-time credential bootstrap using the existing pinned administrative SSH path.
# This is not the routine host installer; it only adds the dedicated CI public key.
set -euo pipefail
[[ $# == 1 && -f $1 && ! -L $1 ]] || { echo 'Provide the dedicated CI public-key file' >&2; exit 2; }
capacity_public_key=$(cat -- "$1")
[[ $capacity_public_key =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+\ homelab-capacity-ci$ ]] || exit 2
ssh-keygen -lf "$1" >/dev/null
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=15 root@pve.tail2f646b.ts.net \
  "bash -s -- '$capacity_public_key'" <<'REMOTE'
set -euo pipefail
[[ $(id -u) == 0 && $(hostname -s) == pve ]]
[[ -d /root/.ssh && ! -L /root/.ssh ]]
# Proxmox manages this exact symlink through its cluster filesystem.
[[ -L /root/.ssh/authorized_keys && $(readlink /root/.ssh/authorized_keys) == /etc/pve/priv/authorized_keys ]]
authorized=/etc/pve/priv/authorized_keys
[[ -f $authorized && ! -L $authorized && $(stat -c %U "$authorized") == root ]]
exec 9>/run/lock/homelab-capacity-ssh.lock
flock -x 9
entry="restrict,from=\"100.64.0.0/10\" $1"
if ! grep -qxF -- "$entry" "$authorized"; then
  # Refuse a different existing enrollment of this identity instead of widening it.
  key_material=$(printf '%s' "$1" | cut -d ' ' -f 2)
  ! grep -qF -- "$key_material" "$authorized"
  printf '\n%s\n' "$entry" >> "$authorized"
fi
printf 'PASS: dedicated capacity CI key enrolled with tailnet source and forwarding restrictions\n'
REMOTE
