#!/usr/bin/env bash
# Application-consistent capture. Run as a separate process, never source this file.
set -euo pipefail
umask 077
if [[ $# != 2 || $1 != age1* ]]; then
  printf 'Usage: bash scripts/odysseus-backup.sh AGE_PUBLIC_RECIPIENT NEW_OUTPUT_DIRECTORY\n' >&2
  exit 2
fi
recipient=$1
output=$2
root=$(cd "$(dirname "$0")/.." && pwd)
for tool in kubectl age shasum; do command -v "$tool" >/dev/null; done
[[ ! -e "$output" ]] || { printf 'Output directory must not exist.\n' >&2; exit 1; }
[[ -z "$(kubectl -n homelab-models get pod odysseus-backup --ignore-not-found -o name)" ]] || {
  printf 'Existing backup pod: investigate before proceeding.\n' >&2; exit 1;
}
app_replicas=$(kubectl -n homelab-models get deployment odysseus -o jsonpath='{.spec.replicas}')
chroma_replicas=$(kubectl -n homelab-models get deployment chromadb -o jsonpath='{.spec.replicas}')
[[ "$app_replicas" =~ ^[01]$ && "$chroma_replicas" =~ ^[01]$ ]] || exit 1
mkdir -m 700 "$output"
# Capture exact inventory before stopping the HTTP client, without model blobs.
kubectl -n homelab-models exec deployment/odysseus -- python -c \
  'import urllib.request; print(urllib.request.urlopen("http://ollama:11434/api/tags", timeout=30).read().decode())' > "$output/models.json"
git -C "$root" rev-parse HEAD > "$output/revision.txt"
cleanup() {
  result=$?
  trap - EXIT INT TERM
  set +e
  kubectl -n homelab-models delete pod odysseus-backup --ignore-not-found --wait=true --timeout=120s
  if ! kubectl -n homelab-models scale deployment/odysseus --replicas="$app_replicas"; then result=1; fi
  if ! kubectl -n homelab-models scale deployment/chromadb --replicas="$chroma_replicas"; then result=1; fi
  if [[ "$app_replicas" == 1 ]]; then
    kubectl -n homelab-models rollout status deployment/odysseus --timeout=600s || result=1
  fi
  if [[ "$chroma_replicas" == 1 ]]; then
    kubectl -n homelab-models rollout status deployment/chromadb --timeout=600s || result=1
  fi
  if [[ "$result" != 0 ]]; then printf 'Backup or service recovery failed; check replica counts before retrying.\n' >&2; fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
kubectl -n homelab-models scale deployment/odysseus --replicas=0
kubectl -n homelab-models wait --for=delete pod -l app=odysseus --timeout=180s
kubectl -n homelab-models scale deployment/chromadb --replicas=0
kubectl -n homelab-models wait --for=delete pod -l app=chromadb --timeout=180s
kubectl create -f "$root/config/environments/kubernetes/homelab/recovery/snapshot-pod.yaml"
kubectl -n homelab-models wait --for=condition=Ready pod/odysseus-backup --timeout=300s
kubectl -n homelab-models exec -i odysseus-backup -- sh -c 'cat > /tmp/models.json' < "$output/models.json"
kubectl -n homelab-models exec -i odysseus-backup -- sh -c 'cat > /tmp/revision.txt' < "$output/revision.txt"
# No decrypted workspace archive touches the administration computer's disk.
kubectl -n homelab-models exec odysseus-backup -- \
  tar -czf - -C /tmp models.json revision.txt -C /snapshot workspace chromadb |
  age -r "$recipient" -o "$output/workspace.tar.gz.age"
shasum -a 256 "$output/workspace.tar.gz.age" > "$output/checksum.txt"
printf 'Encrypted capture complete at %s. Upload and isolated restore remain required.\n' "$output"
