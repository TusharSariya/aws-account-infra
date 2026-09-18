# Design: migrate homelab ingress to Istio (Grafana over Gateway API)

> [!IMPORTANT]
> Historical record only. This document describes the retired Ubuntu/kubeadm and Ansible path. Its commands are archival examples and must not be run. Removed sources remain available in the [pre-removal repository tree](https://github.com/TusharSariyaOrg/aws-account-infra/tree/9a5f9720e45e3bbcbb5637e7bd27a8c688d53add/ansible). Current server management uses Talos, OpenTofu, and Helm.

- **Date:** 2026-07-06
- **Status:** Approved (design); pending implementation plan
- **Branch:** `chore/multi-environment-infra`
- **Author:** Tushar Sariya (with Claude)

## Context

The homelab single-node cluster (`ubuntu-desktop`, k8s v1.36.2) currently exposes
Grafana through **Envoy Gateway** using the Kubernetes Gateway API. That migration
(from the retired ingress-nginx) succeeded: Gateway `gateway-system/homelab` is
`Programmed=True` on MetalLB address `10.0.0.233`, and the Grafana `HTTPRoute`
(`grafana.home.arpa`) is Accepted. `ingress-nginx` is still installed at
`10.0.0.231` pending removal.

The owner wants to adopt **Istio** as the cluster's service-mesh platform, driven
by a planned modular RAG pipeline (harvest → extract → chunk → embed → query)
whose **query serving path** is the part a mesh genuinely benefits. As the first,
low-risk step toward that platform, Istio will take over **north-south ingress**,
starting with Grafana. This is deliberately an ingress task; the east-west mesh is
future work.

### Relevant current state (verified live)

- Node `ubuntu-desktop` Ready; containerd 2.2.2.
- Cilium CNI: `kubeProxyReplacement: false`, `routingMode: tunnel` (VXLAN),
  version 1.19.5. **This datapath makes Istio sidecar mode the safe choice and
  ambient mode the risky combo** (ztunnel + istio-cni node redirection conflicts
  with Cilium/VXLAN).
- MetalLB pool `homelab`: `10.0.0.231-10.0.0.253` (auto-assign on). In use:
  `.231` ingress-nginx, `.232` Pi-hole, `.233` Envoy Gateway. `.234-.253` free.
- Pi-hole (`10.0.0.232`) is the Mac's live Wi-Fi DNS and holds the record
  `grafana.home.arpa → 10.0.0.233`. It is managed manually via
  `kubernetes/apps/pihole/pihole.yml` (`FTLCONF_dns_hostRecord=...`), not by
  Ansible.
- kube-prometheus-stack healthy in `monitoring`; Grafana Service
  `kube-prometheus-stack-grafana:80` (ClusterIP).

## Goal

Replace the cluster's north-south ingress with Istio: serve `grafana.home.arpa`
over HTTP through an Istio ingress gateway using the standard Gateway API, then
retire Envoy Gateway and ingress-nginx — with zero Grafana downtime and a safe,
verify-before-remove cutover. All work stays within the Ansible `cluster_addons`
role, consistent with how every other in-cluster addon is managed.

## Non-goals (explicit)

- **No HTTPS/TLS yet.** Grafana stays HTTP-only (matches current behaviour).
  HTTPS is the first follow-up.
- **No workload sidecar injection.** istiod is installed sidecar-capable, but no
  namespace is labeled for injection. The mesh (east-west) is separate future work.
- **No ambient mode.** Explicitly deferred due to the Cilium/VXLAN datapath.
- **No Terraform/OpenTofu.** See "IaC boundary" below.
- **No Pi-hole re-architecture.** Only its Grafana DNS record changes.

## Decisions (locked)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Fate of existing ingress | **Istio replaces it** — retire Envoy Gateway + ingress-nginx |
| 2 | Ingress API | **Kubernetes Gateway API** (not Istio classic `Gateway`/`VirtualService`) |
| 3 | Istio data-plane mode | **Sidecar** (ingress-only now; injection off) |
| 4 | Grafana transport | **HTTP-only** now; HTTPS deferred |
| 5 | Cutover strategy | **Parallel on a new IP** (`10.0.0.234`) + Pi-hole DNS flip |

## IaC boundary: why Ansible, not Terraform/OpenTofu

This repo has a clean, deliberate separation that this work must preserve:

- **OpenTofu/Terraform → AWS cloud provisioning only.** `deploy-units.json`
  contains exclusively AWS roots (`aws-staging-account`, `aws-staging-rag`) under
  `live/aws/` with `modules/aws/`. There is no Tofu-touches-Kubernetes path today.
- **Ansible `cluster_addons` → the entire homelab cluster.** Cilium, MetalLB,
  metrics-server, local-path, GPU operator, Envoy Gateway, kube-prometheus-stack,
  plus kubectl-applied Gateway/MetalLB manifests all flow through one role.

Istio is an in-cluster addon exactly like Envoy Gateway, so it belongs in
`cluster_addons`. Putting it in Tofu would invent a new boundary crossing and
reintroduce problems the Ansible path already solved — notably CRD-before-CR
ordering (Tofu's `kubernetes_manifest` needs CRDs at plan time) and perpetual
state drift on controller-mutated fields (Gateway status, MetalLB IP assignment,
Istio-injected fields).

**Boundary rule:** Tofu stops at the cluster edge; Ansible + Helm own inside it.
Tofu enters *beside* this work only when cloud resources appear — e.g. public DNS
(Route53), public certs (ACM) for HTTPS, workload identity (IAM), or a RAG
vector-DB backing store (RDS/OpenSearch/S3) — as new `deploy-units.json` roots
consumed by Ansible via outputs. None apply to a LAN-only `grafana.home.arpa`
today.

## Target architecture

```
                 ┌─────────────────────────────────────────┐
   laptop  ────► │  Istio ingress gateway (Envoy)           │
   grafana       │  MetalLB LoadBalancer 10.0.0.234, HTTP:80│
   .home.arpa    │  GatewayClass: istio, listener "http"    │
                 └───────────────┬─────────────────────────┘
                                 │ HTTPRoute grafana.home.arpa
                                 ▼
              kube-prometheus-stack-grafana:80  (monitoring ns)

  Control plane: istiod (sidecar mode, no injection)
  Removed:       Envoy Gateway (gateway-system) + ingress-nginx
  Unchanged:     Pi-hole, monitoring stack, Cilium/MetalLB/GPU/storage
```

## Detailed changes (all in `ansible/roles/cluster_addons`, except Pi-hole DNS)

### 1. `templates/helmfile.yaml.j2`

- Add the Istio chart repository
  (`https://istio-release.storage.googleapis.com/charts`).
- Add two pinned releases in namespace `istio-system`:
  - `base` — Istio CRDs + cluster roles.
  - `istiod` — control plane, sidecar profile (with the Gateway API deployment
    controller enabled, which recent Istio does by default).
- **Do not** install a separate `gateway` chart. Because we use Gateway API,
  Istio auto-provisions the ingress gateway Deployment + LoadBalancer Service
  directly from the `Gateway` resource (§3), in the Gateway's namespace
  (`istio-ingress`).
- **Remove** the `envoy-gateway` release.
- Leave every other release (Cilium, MetalLB, metrics-server, local-path,
  gpu-operator, kube-prometheus-stack) untouched.

### 2. `tasks/main.yml` — CRD handling

- The current single step installs **Gateway API standard-channel + Envoy
  Gateway** CRDs from the Envoy `gateway-crds-helm` chart. Decouple it:
  - Keep installing **Gateway API standard-channel CRDs**, but from the upstream
    Gateway API release (pinned), independent of Envoy.
  - Istio's own CRDs come from the `base` chart (Helmfile), not this step.
- Remove the Envoy CRD download/template/apply steps and the Envoy
  `helm pull` step.
- Add removal steps (see §5).

### 3. `templates/gateway-resources.yml.j2`

- Replace the `envoy` GatewayClass and its Gateway with:
  - **GatewayClass `istio`** — `controllerName: istio.io/gateway-controller`.
  - **Gateway** (namespace `istio-ingress` via
    `{{ cluster_addons_gateway_namespace }}`, name
    `{{ cluster_addons_gateway_name }}`), `gatewayClassName: istio`, one listener
    **named `http`** (HTTP:80), `allowedRoutes.namespaces.from: All`, and the
    MetalLB IP request for `{{ cluster_addons_gateway_address }}` (`.234`).
    Applying this Gateway is what triggers Istio to auto-provision the ingress
    data plane (Deployment + LoadBalancer Service) in `istio-ingress`.
- The **Grafana `HTTPRoute` is retained almost verbatim** — same `sectionName:
  http`, hostname, and `backendRef` to `kube-prometheus-stack-grafana:80`; only
  its parent Gateway identity changes (via the shared vars).

### 4. `defaults/main.yml`

- Add `cluster_addons_istio_version` (pinned).
- Existing `cluster_addons_gateway_*` vars already derive from the
  `kubernetes_gateway_*` inventory vars — these get repointed in local inventory
  (see §6), so the templates need no hardcoded gateway identity change.

### 5. `tasks/main.yml` — verification & removal (verify-before-remove)

Mirror the existing safety pattern, retargeted at Istio:

- Wait for the Istio Gateway `Programmed=True`.
- Wait for the Grafana `HTTPRoute` `Accepted=True`.
- `uri` check: `http://<istio-gateway-ip>/login`, `Host: grafana.home.arpa`,
  expect 200 — **before any removal**.
- Only then: `helm uninstall envoy-gateway -n envoy-gateway-system`, and keep the
  existing ingress-nginx removal task (which already gates on `helm status`).

### 6. Local inventory (ignored by Git — not committed)

Repoint the shared gateway vars to Istio:

```yaml
kubernetes_gateway_namespace: istio-ingress  # gateway data plane, separate from istio-system
kubernetes_gateway_name: homelab             # Istio Gateway resource name
kubernetes_gateway_address: "10.0.0.234"
kubernetes_grafana_hostname: grafana.home.arpa
```

### 7. `cluster_validation` role — no file changes

The role is already gateway-agnostic: it reads the gateway by
`kubernetes_gateway_*`, asserts `Programmed` + a MetalLB address, and runs a
disposable Gateway-API `HTTPRoute` smoke test with `sectionName: http`. Because
the Istio Gateway keeps a listener named `http` and `allowedRoutes.from: All`,
the smoke test exercises Istio automatically once the inventory vars are
repointed. (Its files are already on the Gateway-API path from the Envoy work.)

### 8. Pi-hole DNS record (manual, matches current management)

- Edit `kubernetes/apps/pihole/pihole.yml`:
  `FTLCONF_dns_hostRecord=grafana.home.arpa,grafana,10.0.0.234`.
- `kubectl apply` it (brief Pi-hole restart → short Mac DNS blip).

## Cutover sequence

1. Install Gateway API CRDs (decoupled) + Istio (`base`, `istiod`) via Helmfile.
   Envoy Gateway stays live on `.233`.
2. Apply the `istio` GatewayClass, the `Gateway` (which auto-provisions the
   ingress gateway Deployment + LoadBalancer on `.234`), and the retargeted
   Grafana HTTPRoute.
3. Verify Grafana through `.234` (Ansible `uri` 200 check). Both gateways up →
   zero downtime.
4. **Manual:** flip Pi-hole record to `.234`, apply, verify `grafana.home.arpa`
   resolves and loads from the laptop.
5. Retire Envoy Gateway (`helm uninstall`) → frees `.233`; retire ingress-nginx
   → frees `.231`.
6. Re-run static checks and `cluster_validation`.

## Validation

- Static: `ansible-playbook playbooks/addons.yml --syntax-check`,
  `playbooks/validate.yml --syntax-check`, `ansible-lint`, `git diff --check`,
  Helmfile build/template render, Jinja render of gateway resources.
- Live: Gateway `Programmed`, HTTPRoute `Accepted`, `uri` 200 to
  `/login`; `dig @10.0.0.232 grafana.home.arpa` → `.234`; `curl` via IP+Host and
  via hostname both 200.
- `cluster_validation` (connectivity test disabled via JSON extra-vars) exercises
  the disposable HTTPRoute through the Istio gateway.

## Rollback

Because cutover is parallel and non-destructive until step 5:

- Before the DNS flip: Grafana still served by Envoy Gateway on `.233`; abort by
  deleting the Istio Gateway/route and uninstalling Istio.
- After the DNS flip but before removal: revert the Pi-hole record to `.233`.
- The Envoy Gateway approach was uncommitted (never in git history); it is
  reconstructable from this spec and the session record if a later re-add is
  needed, but not via `git`.

## Out of scope / follow-ups (tracked)

1. **HTTPS** on the Istio gateway (TLS listener + cert-manager/local CA; public
   certs later = Route53/ACM via Tofu). First follow-up.
2. Pin Pi-hole to an immutable image digest.
3. RAG mesh: workload sidecar injection, east-west mTLS, query-path traffic
   management, and OpenTelemetry tracing — separate spec.
4. Reclaim/renumber freed MetalLB addresses (`.231`, `.233`) if desired
   (cosmetic).

## Known unknowns to confirm during planning

- **MetalLB IP assignment on the Istio Gateway's auto-provisioned Service.** Envoy
  Gateway used `spec.infrastructure.annotations` for `metallb.io/loadBalancerIPs`.
  Confirm whether the target Istio version propagates Gateway `infrastructure`
  annotations to the generated Service; fallback is a Service annotation or a
  MetalLB pool/`L2Advertisement` selector.
- **Exact Istio version pin** — select the latest stable Istio that supports
  k8s 1.36 and Gateway API standard channel; record the pin in `defaults`.
- **Gateway API CRD source** — confirm the pinned upstream standard-channel URL
  and that Istio does not also try to manage those CRDs.

## Files touched (summary)

Modified:
- `ansible/roles/cluster_addons/templates/helmfile.yaml.j2`
- `ansible/roles/cluster_addons/templates/gateway-resources.yml.j2`
- `ansible/roles/cluster_addons/tasks/main.yml`
- `ansible/roles/cluster_addons/defaults/main.yml`
- `kubernetes/apps/pihole/pihole.yml` (DNS record only)

Unchanged but relevant: `cluster_validation` role (var-driven), local inventory
(ignored by Git), `deploy-units.json` (no Tofu changes).

## As-built (2026-07-06)

Delivered and verified live. Notes vs. the design above:

- **Pins:** Istio `1.30.2` (base + istiod); Gateway API standard-channel CRDs
  `v1.5.1` (matched what was already on the cluster), installed from upstream and
  decoupled from the Envoy CRD chart.
- **GatewayClass:** we do **not** define one. istiod ships a built-in `istio`
  GatewayClass; the Gateway just references it. Defining our own would fight
  istiod for ownership.
- **MetalLB IP:** the known-unknown resolved — Istio propagates the Gateway's
  `spec.infrastructure.annotations` (`metallb.io/loadBalancerIPs`) to the
  auto-provisioned Service, and MetalLB assigned `10.0.0.234` cleanly.
- **Pi-hole admin UI added:** a second `HTTPRoute` (`pihole.home.arpa` →
  `pihole:80`) lives in `kubernetes/apps/pihole/pihole.yml`, co-located with the
  app. Pi-hole DNS stays on its LoadBalancer at `10.0.0.232:53`; only the web UI
  is routed. The Pi-hole host record now maps both `grafana.home.arpa` and
  `pihole.home.arpa` to `10.0.0.234`.
- **Incident:** the first playbook run used stale local-inventory values
  (`gateway-system` / `.233`), so the Gateway requested an IP already held by
  Envoy Gateway and never programmed. Fix: repoint the local inventory to
  `istio-ingress` / `.234`; the role's verify-then-remove logic self-healed the
  orphaned resources on the next run. The required local-inventory edit is now
  called out here and in `docs/gateway-api.md`.
- **Final state:** `grafana.home.arpa` and `pihole.home.arpa` both resolve to
  `.234` and return HTTP 200 through Istio; Envoy Gateway and ingress-nginx
  removed; `.231`/`.233` released.
