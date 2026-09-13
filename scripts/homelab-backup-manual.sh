#!/usr/bin/env bash
# Run in a separate bash process; never source into an interactive shell.
set -Eeuo pipefail
umask 077
backup_work=''
backup_mode=${1:-bootstrap}
[[ $# -le 1 && ( "$backup_mode" == bootstrap || "$backup_mode" == --etcd ) ]] || { echo 'Usage: bash scripts/homelab-backup-manual.sh [--etcd]' >&2; exit 1; }
backup_repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
backup_stage='preflight'
report_error() {
  local result=$1 line=$2
  printf 'Backup stopped during %s (exit %s, line %s).\n' "$backup_stage" "$result" "$line" >&2
}
trap 'report_error "$?" "$LINENO"' ERR
trap 'if [[ -n "$backup_work" ]]; then rm -f "$backup_work/source.tar.gz" "$backup_work/restored.tar.gz"; fi' EXIT
for tool in aws age tar cmp; do
  command -v "$tool" >/dev/null || { printf 'Missing command: %s\n' "$tool" >&2; exit 1; }
done
if [[ ! -t 0 ]]; then
  echo 'Run from an interactive terminal so age can prompt for your passphrase.' >&2
  exit 1
fi
printf 'Checking AWS account...\n'
backup_account=$(aws --profile admin sts get-caller-identity --query Account --output text)
[[ "$backup_account" == 992382747916 ]] || { echo 'Unexpected AWS account; stopped.' >&2; exit 1; }
mkdir -p "$HOME/Backups/homelab-recovery"
backup_work=$(mktemp -d "$HOME/Backups/homelab-recovery/backup.XXXXXXXX")
backup_bucket=homelab-recovery-992382747916-us-east-1
backup_prefix=bootstrap
[[ "$backup_mode" != --etcd ]] || backup_prefix=bootstrap/etcd
backup_key="$backup_prefix/$(date -u +%Y%m%dT%H%M%SZ)-$(basename "$backup_work").tar.gz.age"
printf 'Work directory: %s\n' "$backup_work"
backup_stage='packaging'
if [[ "$backup_mode" == --etcd ]]; then
  command -v python3 >/dev/null
  backup_stage='snapshot and metadata verification'
  python3 "$backup_repo/scripts/homelab-etcd-snapshot.py" --output "$backup_work/etcd-bundle"
  COPYFILE_DISABLE=1 tar -czf "$backup_work/source.tar.gz" -C "$backup_work/etcd-bundle" .
else
  printf 'Packaging the selected Talos files and Proxmox baseline...\n'
  COPYFILE_DISABLE=1 tar -czf "$backup_work/source.tar.gz" -C "$HOME" \
    .config/aws-account-infra/talos/homelab/talos-secrets.yaml \
    .config/aws-account-infra/talos/homelab/two-vm-20260912/talos-cp-01.machineconfig.yaml \
    .config/aws-account-infra/talos/homelab/two-vm-20260912/talos-worker-01.machineconfig.yaml \
    .config/aws-account-infra/talos/homelab/two-vm-20260912/talosconfig \
    Backups/proxmox/pve/pve-empty-host-baseline-20260912T210507Z.tar.gz
fi
backup_stage='encryption'
printf 'Encrypting. Enter the passphrase saved in your password manager.\n'
age -p -o "$backup_work/backup.tar.gz.age" "$backup_work/source.tar.gz"
backup_stage='upload'
printf 'Uploading encrypted archive...\n'
backup_version=$(aws --profile admin --region us-east-1 s3api put-object \
  --bucket "$backup_bucket" --key "$backup_key" \
  --body "$backup_work/backup.tar.gz.age" --checksum-algorithm SHA256 \
  --query VersionId --output text)
printf 's3://%s/%s\nVersion: %s\n' "$backup_bucket" "$backup_key" "$backup_version" > "$backup_work/receipt.txt"
if [[ "$backup_mode" == --etcd ]]; then
  cp "$backup_work/etcd-bundle/snapshot-metadata.json" "$backup_work/snapshot-metadata.json"
fi
backup_stage='download'
printf 'Downloading that exact S3 version...\n'
aws --profile admin --region us-east-1 s3api get-object \
  --bucket "$backup_bucket" --key "$backup_key" --version-id "$backup_version" \
  --checksum-mode ENABLED "$backup_work/downloaded.tar.gz.age" > "$backup_work/s3-metadata.json"
backup_stage='decryption and comparison'
printf 'Verifying restore. Enter the same passphrase again.\n'
age -d -o "$backup_work/restored.tar.gz" "$backup_work/downloaded.tar.gz.age"
cmp "$backup_work/source.tar.gz" "$backup_work/restored.tar.gz"
# Remove only this run's temporary plaintext bundle after verified recovery.
if [[ "$backup_mode" == --etcd ]]; then
  rm -rf "$backup_work/etcd-bundle"
fi
printf 'PASS: encrypted backup restored exactly\n' | tee -a "$backup_work/receipt.txt"
cat "$backup_work/receipt.txt"
