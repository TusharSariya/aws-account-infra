# Gateway API

The cluster uses Istio (sidecar mode) as its Gateway API implementation. Istio
provides north-south ingress over the existing Cilium/kube-proxy datapath, so it
replaced both the retired ingress-nginx controller and an interim Envoy Gateway
setup without a disruptive migration to Cilium's kube-proxy replacement or to
Istio's ambient (ztunnel) data plane.

## Why Istio, sidecar mode

- Istio implements the Kubernetes Gateway API and uses Envoy as its data plane.
- Sidecar mode installs a control plane (istiod) plus per-Gateway ingress proxies
  without touching pod-to-pod networking. Ambient mode (ztunnel + waypoints) does
  node-level traffic redirection that conflicts with this cluster's Cilium
  `kubeProxyReplacement: false` + VXLAN tunnel datapath, so it is intentionally
  avoided.
- No workload sidecar injection is enabled yet; only the ingress path is in use.
  Injection can be turned on per namespace when an east-west mesh is needed.

## Managed resources

The `cluster_addons` Ansible role performs the deployment in dependency order:

1. Server-side apply pinned Gateway API standard-channel CRDs (`v1.5.1`).
2. Install pinned Istio `base` and `istiod` (`1.30.2`) through Helmfile. istiod
   provides the built-in `istio` GatewayClass.
3. Create the `homelab` Gateway in the `istio-ingress` namespace referencing the
   `istio` GatewayClass. Istio auto-provisions the ingress Deployment and
   LoadBalancer Service from that Gateway.
4. Request `10.0.0.234` for the generated Service through the Gateway's MetalLB
   infrastructure annotation.
5. Attach the Grafana HTTPRoute for `grafana.home.arpa`.
6. Verify Grafana through the Gateway (HTTP 200) before removing anything.
7. Remove the interim Envoy Gateway and the retired ingress-nginx only after
   verification succeeds.

Environment-specific values live in the inventory:

```yaml
kubernetes_gateway_address: "10.0.0.234"
kubernetes_gateway_namespace: istio-ingress
kubernetes_gateway_name: homelab
kubernetes_grafana_hostname: grafana.home.arpa
```

Reconcile the platform with:

```bash
cd ansible
ansible-playbook playbooks/addons.yml
```

Inspect Gateway status and attached routes:

```bash
kubectl get gatewayclass,gateway -A
kubectl get httproute -A
kubectl describe gateway homelab -n istio-ingress
```

The Gateway currently exposes HTTP on the trusted LAN. Add an HTTPS listener,
certificate automation, and HTTP-to-HTTPS redirect before exposing sensitive
applications — Grafana and the Pi-hole admin UI both send credentials over
plaintext today.

## Application routes

Applications define `HTTPRoute` resources in their own namespaces and attach them
to the shared listener:

```yaml
parentRefs:
  - name: homelab
    namespace: istio-ingress
    sectionName: http
```

The listener permits routes from all namespaces. For example, the Pi-hole admin
UI (deployed by the `cluster_apps` role) exposes `pihole.home.arpa` through the
gateway, while Pi-hole DNS keeps serving on its own LoadBalancer at
`10.0.0.232:53` — only the web UI is routed through Istio; DNS (an L4 service)
is not and must not be.

Access remains controlled by explicit hostnames and application authentication;
Kubernetes NetworkPolicy should be added as application isolation requirements
grow.

## Validation

The cluster validation role creates a disposable HTTPRoute, waits until Istio
accepts it, and sends an HTTP request through the MetalLB address with the
expected Host header. This validates the controller, Envoy data plane, MetalLB
advertisement, route attachment, Service, and backend pod together. It is
gateway-agnostic — it targets whatever `kubernetes_gateway_*` points at.

## References

- [Gateway API](https://gateway-api.sigs.k8s.io/)
- [Istio Kubernetes Gateway API](https://istio.io/latest/docs/tasks/traffic-management/ingress/gateway-api/)
- [Istio Helm installation](https://istio.io/latest/docs/setup/install/helm/)
- [ingress-nginx retirement](https://kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/)
