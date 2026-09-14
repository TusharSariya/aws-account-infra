#!/usr/bin/env bash
# Read-only node and platform readiness; no disposable workloads or reboot.
set -Eeuo pipefail
trap 'echo "ACCEPTANCE_DIAGNOSTIC: readiness line $LINENO" >&2' ERR
: "${KUBECONFIG:?Set KUBECONFIG}"
KUBECTL="${KUBECTL:-kubectl}"
k() { "$KUBECTL" --request-timeout=30s "$@"; }
k wait --for=condition=Ready node/talos-cp-01 node/talos-worker-01 --timeout=300s
for ds in cilium cilium-envoy kube-proxy; do
  k -n kube-system rollout status "daemonset/$ds" --timeout=300s
done
for deploy in cilium-operator coredns; do
  k -n kube-system rollout status "deployment/$deploy" --timeout=300s
done
k -n local-path-storage rollout status deployment/local-path-provisioner --timeout=300s
echo 'PASS: nodes and platform workloads ready'
