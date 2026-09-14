#!/usr/bin/env bash
# Repeatable networking acceptance. Requires KUBECONFIG; creates only an isolated
# temporary namespace and removes it on exit. Does not install or change Cilium.
set -Eeuo pipefail
trap 'echo "ACCEPTANCE_DIAGNOSTIC: network line $LINENO" >&2' ERR
: "${KUBECONFIG:?Set KUBECONFIG to the private homelab kubeconfig}"
KUBECTL="${KUBECTL:-kubectl}"
k() { "$KUBECTL" --request-timeout=30s "$@"; }

bash "$(dirname "$0")/homelab-readiness.sh"
[[ "$(k -n kube-system get cm cilium-config -o jsonpath='{.data.kube-proxy-replacement}')" == false ]]
[[ "$(k -n kube-system get cm cilium-config -o jsonpath='{.data.routing-mode}')" == tunnel ]]
[[ "$(k -n kube-system get cm cilium-config -o jsonpath='{.data.tunnel-protocol}')" == vxlan ]]
[[ "$(k -n kube-system get cm cilium-config -o jsonpath='{.data.ipam}')" == kubernetes ]]

ns=$(python3 "$(dirname "$0")/homelab_fixture.py" --name <<'YAML'
apiVersion: v1
kind: Namespace
metadata:
  generateName: homelab-network-check-
  labels:
    pod-security.kubernetes.io/enforce: restricted
YAML
)
cleanup() { k delete namespace "$ns" --wait=false >/dev/null; }
trap cleanup EXIT
for node in talos-cp-01 talos-worker-01; do
  python3 "$(dirname "$0")/homelab_fixture.py" --namespace "$ns" >/dev/null <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: $node
  labels:
    app: $node
spec:
  nodeSelector:
    kubernetes.io/hostname: $node
  tolerations:
    - key: node-role.kubernetes.io/control-plane
      operator: Exists
      effect: NoSchedule
  automountServiceAccountToken: false
  securityContext:
    runAsNonRoot: true
    runAsUser: 65532
    runAsGroup: 65532
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: http
      image: docker.io/library/busybox:1.37.0@sha256:9db7b59979c38555a39def84a31fb98b5296952f9e3afd4f6f11f05b07adfab0
      command: [sh, -c, 'echo network-ok > /tmp/index.html; exec httpd -f -p 8080 -h /tmp']
      ports:
        - containerPort: 8080
      readinessProbe:
        httpGet:
          path: /
          port: 8080
        initialDelaySeconds: 1
        periodSeconds: 2
      resources:
        requests:
          cpu: 10m
          memory: 16Mi
        limits:
          cpu: 100m
          memory: 32Mi
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: [ALL]
      volumeMounts:
        - name: tmp
          mountPath: /tmp
  volumes:
    - name: tmp
      emptyDir:
        sizeLimit: 16Mi
---
apiVersion: v1
kind: Service
metadata:
  name: $node
spec:
  selector:
    app: $node
  ports:
    - port: 8080
      targetPort: 8080
YAML
done
k -n "$ns" wait --for=condition=Ready pod --all --timeout=180s
for source in talos-cp-01 talos-worker-01; do
  k -n "$ns" exec "$source" -- nslookup kubernetes.default.svc.cluster.local >/dev/null
  k -n "$ns" exec "$source" -- nslookup kubernetes.io >/dev/null
  for target in talos-cp-01 talos-worker-01; do
    pod_ip=$(k -n "$ns" get pod "$target" -o jsonpath='{.status.podIP}')
    for host in "$pod_ip" "$target.$ns.svc.cluster.local"; do
      response=$(k -n "$ns" exec "$source" -- wget -q -T 10 -O - "http://$host:8080/")
      [[ "$response" == network-ok ]]
    done
    echo "PASS: $source -> $target pod IP and DNS/ClusterIP service"
  done
done
echo 'PASS: both nodes ready, Cilium/Envoy/operator/CoreDNS/kube-proxy ready, VXLAN and kube-proxy retained, internal/external DNS and same/cross-node connectivity'
