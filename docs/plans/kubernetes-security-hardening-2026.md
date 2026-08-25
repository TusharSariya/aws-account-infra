# Practical Kubernetes Security Hardening for 2026

## Status

Proposed architecture and rollout record as of August 25, 2026. This document
does not authorize deployment or live infrastructure changes. Revalidate every
component version, feature gate, and compatibility claim immediately before
apply.

The target is a practical, open-source-first posture for the Talos homelab. It
avoids overlapping security platforms when Kubernetes, Talos, Cilium, Kyverno,
Sigstore, Trivy, and Tetragon already cover the required control planes.

## Executive decision

State-of-the-art Kubernetes security in 2026 is not a single product such as
OpenShift or a commercial CNAPP. It is a layered system in which each tool has
one authority:

| Boundary | Authority |
|---|---|
| Human authentication | Authentik OIDC with MFA |
| Kubernetes API authorization | Kubernetes RBAC |
| Workload admission | Pod Security Admission, native CEL policy, and Kyverno |
| Network authorization | Cilium and, where deliberately meshed, Istio |
| Runtime secret source | AWS Secrets Manager through IAM Roles Anywhere and External Secrets Operator |
| Image trust | Sigstore/Cosign artifacts verified by Kyverno |
| Runtime detection | Tetragon |
| Broker resource relationships | OpenFGA |
| Database authorization | PostgreSQL roles, grants, and row-level security |

OpenFGA does not replace Kubernetes RBAC, admission policy, filesystem ACLs, or
PostgreSQL authorization. It remains private behind the workspace broker and
answers application relationship questions about projects, runs, workspaces,
datasets, and artifacts.

The repository is already close to this target. The highest-value next step is
to activate and prove controls that are currently disabled or gated, not add
another policy engine or scanner.

## Current and target state

The repository already contains:

- Pod Security Admission labels using the `restricted` profile.
- Native `ValidatingAdmissionPolicy` controls for vended namespaces.
- Default-deny tenant `NetworkPolicy` resources.
- An API audit policy that omits Secret bodies and captures RBAC, admission,
  network-policy, and interactive access changes.
- Pinned Argo CD and Kyverno definitions, both disabled by default.
- A disabled legacy Kyverno `ClusterPolicy` image-verification template.
- Gated tenant reconciliation requiring evidence of Secret encryption, Argo CD
  readiness, and Kyverno readiness.
- Plans for Authentik, External Secrets Operator, IAM Roles Anywhere, a local
  OCI registry, Hubble, and Tetragon.

There are two intentional Kubernetes states during migration:

- `docs/kubernetes-vending.md` describes the legacy Ubuntu/kubeadm Kubernetes
  1.35 path and its compatible controller pins.
- The Talos rebuild targets Talos 1.13.9, Kubernetes 1.36.3, and Cilium 1.20.1.

Kubernetes 1.36 is authoritative for the new Talos cluster. Keep the 1.35
document as a current-state record until migration completes, then retire it.

## Identity and RBAC

### Human access

- Authenticate ordinary administrators through Authentik OIDC using stable
  subjects, MFA, and short-lived tokens.
- Map prefixed Authentik groups to narrow namespace-scoped RoleBindings.
- Do not map routine users into `system:masters` or distribute static
  cluster-admin kubeconfigs.
- Preserve offline Talos and Kubernetes break-glass credentials because the
  normal identity provider runs inside the environment it protects.
- Restrict the Kubernetes API, Talos API, Proxmox, NAS administration, Argo CD,
  Grafana, and Authentik administration to the LAN or approved tailnet.
- Audit and alert on impersonation, `bind`, `escalate`, CSR approval, token
  creation, RBAC changes, admission-policy changes, and break-glass use.

### Workload identity

- Give every controller and application a dedicated ServiceAccount.
- Set `automountServiceAccountToken: false` by default. Explicitly project
  short-lived, audience-bound tokens only where Kubernetes API access is
  required.
- Do not grant ordinary workloads `get`, `list`, or `watch` on Secrets.
- Permit only restricted Argo CD and broker identities to create workloads in
  sensitive namespaces. Workload-creation permission otherwise provides an
  indirect path to mount every Secret in that namespace.
- Remove broad `nodes/proxy` access. Kubernetes 1.36 monitoring receives only
  the required `nodes/metrics`, `nodes/stats`, `nodes/pods`, or other exact
  kubelet subresources.

See [Kubernetes RBAC good practices](https://kubernetes.io/docs/concepts/security/rbac-good-practices/)
and [fine-grained kubelet authorization](https://kubernetes.io/blog/2026/04/24/kubernetes-v1-36-fine-grained-kubelet-authorization-ga/).

## Workload isolation and admission

### Isolation floor

- Enforce Pod Security Admission `restricted` on application and agent
  namespaces.
- Run trusted workloads on the trusted worker and agent-authored or untrusted
  workloads on the tainted sandbox worker under gVisor.
- Require Kubernetes 1.36 user namespaces with `hostUsers: false` for
  compatible trusted workloads. Pilot stateless workloads first; do not
  require it for gVisor or NFS/CSI workspaces until compatibility tests pass.
- Require non-root execution, runtime-default seccomp, dropped capabilities,
  and a read-only root filesystem where the application supports it.
- Reject privileged containers, privilege escalation, host namespaces, host
  paths, unsafe sysctls, unauthorized RuntimeClasses, unbounded `emptyDir`, and
  undeclared node placement.

User namespaces reached GA in Kubernetes 1.36 and map container identities away
from privileged host identities. See
[Kubernetes user namespaces](https://kubernetes.io/blog/2026/04/23/kubernetes-v1-36-userns-ga/).

### Policy ownership

- Keep Pod Security Admission as the non-negotiable floor.
- Keep native `ValidatingAdmissionPolicy` for simple CEL checks needing no
  external controller.
- Use Kyverno for contextual validation, generation, mutation, reports,
  cleanup, and image verification.
- Upgrade and validate Kyverno for Kubernetes 1.36 before enabling it.
- Migrate the existing `kyverno.io/v1` image `ClusterPolicy` to stable
  `policies.kyverno.io/v1` `ImageValidatingPolicy`. Kyverno 1.18 is the
  transition point; legacy policy types are deprecated in 1.19 and planned for
  removal in 1.20.
- Run new policies in Audit mode, remediate violations, and then fail closed
  for security-critical rules.
- Permit policy exceptions only when namespaced, catalog-declared, approved,
  time-bounded, and audited.

See [Kyverno policy types](https://kyverno.io/docs/policy-types/overview/) and
[ImageValidatingPolicy](https://kyverno.io/docs/policy-types/image-validating-policy/).

### Secret-to-workload authorization

RBAC prevents direct Secret API reads but does not decide which Secret a Pod
may mount. Namespace isolation and admission policy close that gap.

- Place Secrets only in the namespace of their authorized workload trust
  domain.
- Use namespace-scoped External Secrets Operator `SecretStore` resources and
  explicit remote keys, never an unrestricted `ClusterSecretStore`.
- Give each namespace or narrow workload class its own IAM Roles Anywhere role
  and explicit Secrets Manager resource prefixes.
- Generate an admission allowlist mapping namespace plus ServiceAccount to
  exact Secret names and, where practical, exact keys.
- Reject undeclared `secretKeyRef`, `envFrom`, Secret volume, init-container,
  sidecar, and CSI secret references.
- Restrict `pods/exec`, `pods/attach`, `pods/portforward`, and ephemeral
  containers because interactive access can expose mounted values.
- Encrypt Secrets in etcd, encrypt snapshots, and inspect ciphertext before
  declaring the Secret-encryption readiness gate complete.

During a WAN partition, the last valid Kubernetes Secret and local admission
policy remain available. External refresh fails visibly but never deletes the
retained target Secret. New cloud-dependent grants fail closed.

## Network and service protection

### Workload policy

- Preserve default-deny ingress and egress in every managed namespace.
- Replace blanket same-namespace access with explicit pod selectors, protocols,
  and ports for each service path.
- Permit DNS only to CoreDNS. Use Cilium DNS/FQDN policy for approved Supabase,
  AWS, GitHub, package, and API destinations.
- Deny workload access to kubelet, Proxmox, NAS administration, Talos API, node
  management, metadata, and control-plane endpoints unless an exact controller
  requirement is documented.
- Restrict Kubernetes API network reachability as well as RBAC; a mounted token
  must not imply unrestricted network access.
- Enable Hubble Relay after baseline policy is enforced and retain allowed and
  denied flow evidence.

Cilium DNS policy assumes trusted cluster DNS responses. Intercept only CoreDNS
traffic and account for full cluster-domain lookup names. See
[Cilium DNS policy](https://docs.cilium.io/en/stable/security/policy/layer7/).

### Node and service identity

- Enable Cilium host firewall in audit mode per node class.
- Allow only documented Talos management, Kubernetes control-plane, Cilium
  health and VXLAN, DNS, NTP, storage, observability, and tailnet flows.
- Enforce one node class at a time after reboot, upgrade, CNI restart, and WAN
  partition tests pass.
- For genuinely multi-service namespaces already using the Istio data plane,
  enable strict mTLS and default-deny `AuthorizationPolicy`, then permit exact
  service identities and routes.
- Do not inject sidecars into unrelated singleton applications merely to claim
  mesh coverage.

See the [Cilium host firewall](https://docs.cilium.io/en/stable/security/host-firewall/).

## Software supply-chain security

### Build and publication

- Pin GitHub Actions by immutable commit and protect release environments.
- Use GitHub OIDC instead of stored cloud credentials.
- Scan source, dependencies, OpenTofu, manifests, and images with Trivy in CI.
- Produce a CycloneDX SBOM for every application image.
- Generate signed SLSA provenance on hosted GitHub Actions builders. Target
  SLSA Build L2 first.
- Sign image digests and attestations with Cosign keyless signing. Accept only
  the exact protected workflow subject and GitHub OIDC issuer.
- Keep protected branches and required reviews. Renovate may open updates but
  must not auto-merge Talos, Kubernetes, CNI, storage, Gateway, or admission
  controller upgrades.

Provenance protects releases only when consumers verify explicit builder and
source expectations. See [SLSA 1.2](https://slsa.dev/spec/v1.2/) and
[Sigstore verification](https://docs.sigstore.dev/cosign/verifying/verify/).

### Admission and disconnected verification

- Reference every deployed image by digest and prohibit mutable tags.
- Mirror the image, Cosign signature, SBOM, SLSA provenance, vulnerability-scan
  attestation, and verification bundle into the NAS-hosted zot registry.
- Make a release eligible only after all required artifacts exist locally.
- Require Kyverno to verify the approved local registry, GitHub workflow
  identity and issuer, digest, signature, provenance, SBOM, and scan
  attestation.
- Pin the Sigstore trust material needed for offline verification. Admission
  must not depend on ECR, Fulcio, or Rekor during a WAN partition.
- Preserve current and previous known-good releases and pre-pull critical
  images on every eligible node.

## Runtime detection and response

### Tetragon

Deploy Tetragon as the single runtime-security system after Cilium and Hubble
are stable. Do not deploy Falco or KubeArmor at the same time.

Begin in observation mode and detect:

- Unexpected shells and package managers.
- Process credential, capability, namespace, and mount changes.
- `ptrace`, kernel-module activity, runtime-socket access, and sensitive host
  file access.
- Writes to executable paths or application binaries.
- Unexpected outbound connections and behavior inconsistent with network
  policy.
- Events correlated to namespace, Pod, ServiceAccount, image digest, and node
  class.

Validate visibility inside gVisor before treating Tetragon as a sandbox
detection boundary. Promote only deterministic, low-false-positive rules to
enforcement, starting with runtime sockets and known sensitive host paths.

See [Tetragon tracing policy](https://tetragon.io/docs/concepts/tracing-policy/)
and [runtime enforcement](https://tetragon.io/docs/concepts/enforcement/).

### Audit and alerts

- Retain Kubernetes audit logs, Hubble flows, Kyverno PolicyReports,
  Authentik events, External Secrets status, and Tetragon events in Loki.
- Never log Secret or credential-bearing request bodies.
- Route alerts through Alertmanager's modular receivers, with email as the only
  initially enabled receiver.
- Alert on RBAC escalation, admission-policy changes, Secret enumeration,
  interactive exec, break-glass use, unsigned images, policy exceptions,
  unexpected egress, runtime detections, stale Secrets, and missing audit
  events.
- Send a dead-man signal externally so total homelab loss is distinguishable
  from a quiet cluster.
- Run periodic read-only Trivy cluster scans and Talos checklist validation
  without another persistent posture-management controller.

## Recovery as a security control

- Encrypt and export Talos etcd snapshots outside the cluster.
- Store recovery identities, Talos machine secrets, trust roots, and
  decryption material separately from ordinary NAS mirrors.
- Restore into a disposable environment and prove encryption, RBAC, admission,
  and audit configuration survive.
- Use application-native database backups, not copies of live database files.
- Keep the local OCI registry and retained Secrets sufficient to restart
  critical workloads without AWS.
- Test revocation while connected and fail-closed behavior while Authentik,
  OpenFGA, AWS, or the broker is unavailable.

Security controls that cannot be recovered predictably are incomplete.

## Rollout sequence

### 1. Establish the baseline

- Treat Talos Kubernetes 1.36.3 as the target and kubeadm 1.35 as temporary
  legacy state.
- Revalidate every platform component for the target versions.
- Remove `nodes/proxy`, wildcard, impersonation, escalation, and unnecessary
  Secret RBAC.
- Verify API audit logging, etcd encryption, encrypted snapshots, and offline
  break-glass access.

### 2. Enforce admission and Secret boundaries

- Upgrade and enable Kyverno in Audit mode.
- Migrate policies to stable CEL-based APIs.
- Add workload, scheduling, Secret-reference, and exception controls.
- Remediate findings and enforce security-critical rules.

### 3. Reduce network reachability

- Replace same-namespace allow-all with declared service paths.
- Add DNS/FQDN restrictions and sensitive-destination denies.
- Enable Hubble, then roll the host firewall from audit to enforcement.

### 4. Enforce artifact provenance

- Add Trivy, SBOM, SLSA, and Cosign stages to protected releases.
- Mirror complete verification artifacts locally.
- Audit image verification online and offline, then deny unverified releases.

### 5. Add runtime detection

- Deploy Tetragon in observation mode.
- Baseline upgrades, backups, restores, applications, and sandbox jobs.
- Route high-confidence detections to email.
- Enable only narrowly tested enforcement rules.

## Acceptance tests

### Identity and API

- Ordinary OIDC administrators cannot obtain `system:masters` authority.
- Monitoring works without `nodes/proxy`.
- ServiceAccounts without explicit projection receive no API token.
- Unauthorized interactive access, impersonation, token creation, and RBAC
  escalation fail and generate audit events.
- Offline break-glass access works and alerts when observability is available.

### Workloads and Secrets

- Privileged, host-mounted, host-networked, incorrectly scheduled, or
  improperly sandboxed Pods are denied.
- Compatible trusted Pods use `hostUsers: false`; sandbox Pods require gVisor.
- Two project workloads cannot mount each other's Secrets.
- Direct Secret API reads remain denied.
- A principal cannot bypass Secret restrictions with an exfiltration Pod.
- ESO provider failure preserves the last value and raises a stale alert.

### Network and artifacts

- Undeclared ingress and egress are denied and visible in Hubble.
- Workloads cannot reach node, kubelet, Proxmox, NAS, or metadata endpoints.
- Mutable, unsigned, wrongly signed, or incompletely attested images are denied.
- Approved releases restart from the local registry without WAN access.

### Runtime and recovery

- Tetragon detections reach Loki and email without exposing Secret values.
- Enforcement blocks only the declared sensitive operation.
- Sandbox testing records which gVisor activity host eBPF can observe.
- An encrypted etcd snapshot restores into a disposable Talos environment.
- RBAC, admission, network policy, local images, and retained Secrets continue
  working while AWS, Authentik, OpenFGA, and the broker are unavailable.

## Explicit deferrals

- Do not replace Talos with OpenShift merely for an integrated security suite.
- Do not add OPA Gatekeeper alongside Kyverno.
- Do not add Falco or KubeArmor alongside Tetragon.
- Do not add Vault solely as a production checkbox.
- Defer SPIFFE/SPIRE until workloads require certificate identities beyond the
  existing Istio and projected-token paths.
- Defer confidential containers until compatible hardware and a concrete
  confidentiality threat exist.
- Keep Kubernetes 1.36 manifest-based admission control sandbox-only while it
  is alpha.
- Add a posture operator or commercial CNAPP only for a measured inventory,
  compliance, or response need.

## Assumptions

- One Proxmox server remains a single physical and administrative failure
  domain.
- Trusted and untrusted workloads remain separated between worker VMs.
- AWS Secrets Manager remains authoritative while retained Kubernetes Secrets
  support disconnected operation.
- The local OCI registry mirrors only allowlisted, verified releases.
- Email is the only initially enabled alert receiver.
- This document introduces no live credential, certificate, key, token,
  password, or Secret value.
