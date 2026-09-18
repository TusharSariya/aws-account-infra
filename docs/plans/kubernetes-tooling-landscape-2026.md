# Kubernetes Tooling Landscape for 2026

## Status

Research and decision record as of August 25, 2026. This document compares
current Kubernetes platforms and ecosystem tooling. It does not authorize a
deployment or replace component-specific compatibility checks before apply.

Official project and vendor documentation is authoritative for lifecycle,
security, and compatibility claims. Reddit links in this document represent
practitioner sentiment and recurring homelab patterns, not reliability or
adoption measurements.

## Executive decision

Keep Talos as the Kubernetes substrate for this Proxmox homelab. Do not replace
it with OpenShift merely to make the environment more production-like.

The detailed disconnected-operation design is documented in
[Seven-day WAN partition resilience](network-partition-resilience.md).
The prioritized security controls and acceptance tests are documented in
[Practical Kubernetes security hardening for 2026](kubernetes-security-hardening-2026.md).
The adoption gates for optional projects such as Agent Sandbox, vCluster,
Kueue, Argo Workflows, and AI-serving tools are documented in
[Additional Kubernetes tooling for 2026](kubernetes-additional-tools-2026.md).

The strongest production pattern in 2026 is not a single product. It is a
deliberately composed platform built around:

- Immutable or provider-managed Kubernetes nodes.
- GitOps reconciliation.
- Gateway API rather than legacy Ingress resources.
- eBPF networking and network observability.
- Workload identity and short-lived credentials.
- Native and policy-controller admission controls.
- OpenTelemetry-compatible instrumentation.
- Signed artifacts, SBOMs, and admission-time verification.
- Tested, application-aware recovery.

OpenShift is a valid enterprise platform, but it optimizes for an integrated,
supported Red Hat operating model. Talos optimizes for a small, immutable,
API-managed Kubernetes substrate whose surrounding platform components remain
independently selectable. The latter matches this repository's goals better.

## Kubernetes platforms and distributions

These products operate at different layers and should not be compared as if
they were interchangeable Kubernetes add-ons.

| Platform | Category | Best fit | Homelab assessment |
|---|---|---|---|
| Amazon EKS, Google GKE, Azure AKS | Cloud-managed Kubernetes | Production in the corresponding public cloud | Useful as an external comparison target, not for the local server |
| Red Hat OpenShift | Integrated enterprise Kubernetes platform | Regulated, on-premises, hybrid, and Red Hat-standardized organizations | Deploy only to learn OpenShift specifically |
| OKD | Community distribution upstream of OpenShift | OpenShift experimentation without Red Hat support | Viable disposable learning cluster, still resource intensive |
| SUSE Rancher | Multi-cluster management platform | Central management of multiple supported downstream clusters | Unnecessary for one cluster |
| RKE2 | Hardened Kubernetes distribution | Supported on-premises, government, and Rancher-managed environments | Strong Talos alternative, but not a reason to rebuild the current design |
| k3s | Lightweight Kubernetes distribution | Edge, small nodes, simple labs, and mixed-use Linux hosts | Best simplicity-first alternative |
| Talos Linux | Immutable Kubernetes operating system | Dedicated Kubernetes machines and VMs | Recommended for this architecture |
| Canonical Kubernetes and MicroK8s | Ubuntu-oriented distributions | Ubuntu estates, appliances, edge, and development | Reasonable alternative with a different lifecycle model |
| Amazon EKS Anywhere | AWS-oriented on-premises distribution | AWS-standardized hybrid environments and data-sovereignty requirements | More machinery than this single cluster requires |
| VMware Cloud Foundation and VKS | Kubernetes integrated with VMware infrastructure | Existing VMware Cloud Foundation customers | Poor greenfield homelab fit |
| Nutanix Kubernetes Platform | Commercial hybrid and multicloud platform | Existing Nutanix estates and managed edge fleets | Excessive for this homelab |
| Spectro Cloud Palette | Cluster-fleet and edge lifecycle platform | Large distributed and intermittently connected edge fleets | Useful product to study, not required here |
| Flatcar Container Linux | Immutable container operating system | Teams that want to assemble Kubernetes separately | More OS flexibility and more assembly work than Talos |

### OpenShift

OpenShift is Kubernetes plus an opinionated enterprise application platform.
It integrates Red Hat Enterprise Linux CoreOS, CRI-O, cluster Operators,
coordinated upgrades, authentication, networking, monitoring, a developer
console, Operator Lifecycle Manager, and other supported platform services.
OpenShift Platform Plus adds products for multicluster management, security,
registry, and data services. See the [OpenShift architecture
overview](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/html/architecture/architecture).

This integration is valuable when an organization wants:

- One vendor accountable for a tested platform.
- Strong defaults and enterprise support.
- Red Hat ecosystem integration.
- Coordinated cluster and operating-system upgrades.
- Compliance-oriented capabilities and certifications.
- A consistent environment across on-premises and supported clouds.

It also imposes a meaningful footprint. OpenShift 4.20 documents minimums of
4 CPU, 16 GB RAM, and 100 GB storage for each conventional control-plane
machine, plus worker capacity. Even a single-node deployment remains a
substantial cluster. Storage latency is especially important for etcd. See the
[OpenShift bare-metal requirements](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/html-single/installing_on_bare_metal/installing_on_bare_metal).

OpenShift is therefore appropriate as a separate, disposable learning target
if OpenShift employment skills are a goal. It should not replace the Talos
cluster solely because it is perceived as more enterprise-grade.

### Rancher, RKE2, and k3s

Rancher is a management plane, not a Kubernetes distribution. It provides
centralized cluster inventory, access, policy, applications, and lifecycle
operations. RKE2 is SUSE's security and compliance-oriented Kubernetes
distribution; k3s is its smaller edge and lab distribution. See the [RKE2
introduction](https://docs.rke2.io/) and [Rancher
overview](https://ranchermanager.docs.rancher.com/getting-started/overview).

Rancher plus RKE2 is one of the strongest conventional on-premises production
alternatives to OpenShift. Rancher is most useful when several downstream
clusters require common management. A community import of a Talos cluster may
work, but Talos is not a named Rancher Prime-certified downstream distribution
in the current support matrix. Do not treat that pairing as a supported
production design.

### Talos and k3s

Talos is the preferred fit when each machine or VM is a dedicated Kubernetes
appliance. Its minimal, immutable, no-SSH operating model reduces node drift
and makes lifecycle operations API-driven. Talos recommends 4 cores and 4 GiB
for a control plane while documenting lower minimums, leaving room to size the
homelab control plane according to measured load. See [Talos system
requirements](https://docs.siderolabs.com/talos/v1.11/getting-started/system-requirements).

k3s is the preferred simplicity-first option for low-resource nodes, familiar
Debian or Ubuntu administration, or hosts that also perform non-Kubernetes
jobs. It is not inherently less legitimate; it makes a different tradeoff
between appliance-style immutability and conventional Linux operability.

## State-of-the-art component choices

### Delivery and configuration

| Need | Preferred choice | Notes |
|---|---|---|
| Continuous delivery | Argo CD | Strong UI, ApplicationSets, sync waves, and clear application health |
| GitOps alternative | Flux | Strong modular and CLI-oriented alternative with good OCI workflows |
| First-party configuration | Kustomize | Use bases and environment overlays |
| Third-party packaging | Helm | Pin chart versions and review values |
| Dependency updates | Renovate | Open reviewable update pull requests; do not blindly auto-merge platform upgrades |
| CI | GitHub Actions | Build, test, scan, sign, and update Git; let GitOps perform deployment |
| Progressive delivery | Argo Rollouts | Add only for an actual canary or blue-green workload |

Argo CD and Flux are both CNCF-graduated GitOps systems. Choosing one is more
important than operating both. This repository should retain Argo CD because
its application visibility and future preview-environment support match the
platform-engineering goal. See the [CNCF GitOps comparison](https://www.cncf.io/blog/2025/06/09/gitops-in-2025-from-old-school-updates-to-the-modern-way/).

### Networking and application exposure

| Need | Preferred choice | Notes |
|---|---|---|
| CNI and NetworkPolicy | Cilium | Retain the existing choice |
| Network-flow visibility | Hubble | Enable after baseline policies exist |
| LAN service addresses | MetalLB L2 | Move to BGP only if the physical network justifies it |
| Routing API | Gateway API | Current standard for role-oriented L4 and L7 routing |
| Gateway implementation | Cilium, Envoy Gateway, or Istio | Select one implementation for a route |
| Certificates | cert-manager | Use DNS-01 and explicit issuer boundaries |
| Selected public access | Cloudflare Tunnel | Declare and approve each hostname individually |

Community ingress-nginx was retired in March 2026 and no longer receives fixes
or security updates. New designs should use Gateway API or another actively
maintained controller. See the [Ingress NGINX retirement
notice](https://kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/).

Gateway API v1.6 promoted TCPRoute and UDPRoute to its Standard channel in
addition to its existing HTTP and TLS routing model. See the [Gateway API v1.6
release](https://kubernetes.io/blog/2026/08/03/gateway-api-v1-6-release/).

Cilium plus Hubble is a strong integrated choice for CNI, policy, optional
kube-proxy replacement, Gateway API, and eBPF flow visibility. See the [Hubble
documentation](https://docs.cilium.io/en/stable/observability/hubble/).

The repository currently selects Istio as its Gateway API implementation.
Retain Istio if service-mesh learning, workload mTLS, and advanced traffic
policy are deliberate goals. If only north-south routing is required, Cilium's
Gateway API implementation would remove a substantial platform component.
Do not operate Istio, Cilium Gateway, and Envoy Gateway simultaneously merely
for feature coverage.

### Authentication, authorization, and policy

| Boundary | Preferred choice |
|---|---|
| Human authentication | Authentik OIDC |
| Kubernetes authorization | Kubernetes RBAC |
| Broker resource relationships | OpenFGA |
| Kubernetes security floor | Pod Security Admission |
| Custom admission and resource policy | Kyverno and CEL-native policy types |
| Workload identity | Projected service-account tokens and external workload identity |

Keep these authorization domains separate. OpenFGA should not replace
Kubernetes RBAC, and Kyverno should not become an application authorization
service.

Native ValidatingAdmissionPolicy is appropriate for simple CEL validation with
no additional controller. Kyverno remains valuable for mutation, generation,
cleanup, reports, and image verification. See [Kyverno policy
types](https://kyverno.io/docs/policy-types/overview/) and [Kyverno image
verification](https://kyverno.io/docs/policy-types/cluster-policy/verify-images/overview/).

Use Tetragon or Falco as an initial runtime-security system, not both. Tetragon
fits naturally with Cilium and eBPF-based observation. Falco provides a mature
detection rule and plugin ecosystem. Begin in observation mode, tune findings,
and validate visibility inside gVisor before enabling enforcement.

### Secrets and AWS access

Use AWS Secrets Manager as the authoritative runtime secret store and External
Secrets Operator to materialize narrowly scoped Kubernetes Secrets. On-premises
AWS access should use dedicated IAM Roles Anywhere identities and short-lived
credentials rather than access keys.

For External Secrets Operator:

- Use a dedicated role, profile, and certificate identity.
- Run the official credential helper through a tightly constrained local
  endpoint.
- Use namespace-scoped `SecretStore` resources.
- Limit each role to explicit secret prefixes and required KMS operations.
- Test certificate rotation, credential refresh, revocation, AWS outage, and
  stale-secret behavior.

External Secrets documents its AWS provider and fine-grained access patterns,
but IAM Roles Anywhere is not presented as a first-class ESO authentication
mode. Treat the credential-helper sidecar as an explicit integration boundary
that requires failure and renewal testing. See the [ESO AWS Secrets Manager
provider](https://external-secrets.io/latest/provider/aws-secrets-manager/)
and [IAM Roles Anywhere credential helper](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/credential-helper.html).

Any future live certificate, private key, password, token, or secret work must
first load the repository-required `aws-secrets-manager` skill and use
`asm-exec` runtime resolution. Secret values must never enter Git, command
arguments, logs, diffs, Terraform output, or agent context.

### Observability

| Signal | Preferred choice |
|---|---|
| Metrics and rules | Prometheus Operator and Prometheus |
| Alert routing | Alertmanager with modular receivers; email first |
| Dashboards | Grafana |
| Logs | Loki initially; VictoriaLogs is a resource-efficient alternative to evaluate |
| Collection | Grafana Alloy or OpenTelemetry Collector |
| Traces | Tempo when an instrumented request path exists |
| Network flows | Hubble |
| Cost and allocation | OpenCost |
| Runtime activity | Tetragon or Falco |
| External availability | Hosted synthetic probe and dead-man heartbeat |

OpenTelemetry should be the application telemetry contract even when Grafana
backends are used. This preserves the ability to change backends without
reinstrumenting applications. See [OpenTelemetry on
Kubernetes](https://opentelemetry.io/docs/platforms/kubernetes/) and [Grafana
Alloy](https://grafana.com/docs/alloy/latest/).

Do not add Tempo until at least one multi-service path emits useful traces. Do
not add Mimir, Thanos, Elasticsearch, OpenSearch, or Pyroscope without a
measured storage, scale, search, or profiling requirement.

### Software supply chain

Use:

- Trivy in CI for image and infrastructure scanning and SBOM production.
- Cosign for image signatures and attestations.
- Kyverno for admission-time verification, keeping one policy engine.
- Digest-pinned deployment images.
- Renovate pull requests for dependencies and base images.
- Protected branches and required CI checks.

Add Trivy Operator only when continuous cluster reports justify another
controller. Add Dependency-Track, Syft, or Grype only when they fill a reporting
or scanner gap instead of duplicating the initial toolchain. See the [Trivy
Operator documentation](https://aquasecurity.github.io/trivy-operator/latest/)
and [Sigstore policy-controller](https://docs.sigstore.dev/policy-controller/overview/).

### Scaling and specialized compute

Use Metrics Server and HPA for ordinary scaling. Add KEDA only for event and
queue-driven workloads. Run VPA in recommendation-only mode before considering
any update mode that can restart or resize workloads. Node autoscalers such as
Karpenter provide little value while all VMs consume one fixed Proxmox host.

Kubernetes 1.36 continues the transition toward Dynamic Resource Allocation
for GPUs and other specialized devices. Stable and beta DRA functionality is
useful for governed device allocation, while newer workload-aware scheduling
features remain experimental. Exercise DRA and Kueue on the sandbox worker only
when real GPU, batch, or AI workloads exist. See the [Kubernetes 1.36 DRA
update](https://kubernetes.io/blog/2026/05/07/kubernetes-v1-36-dra-136-updates/).

### Storage, databases, and recovery

Keep the NAS outside Kubernetes. Use statically brokered NFS CSI volumes for
shared workspaces and project data, local POSIX storage for latency-sensitive
cluster state, and application-native backup mechanisms for databases.

Do not deploy Rook/Ceph merely to replicate data between VMs on one physical
server. Ceph becomes appropriate with at least three independent storage nodes,
disks, and meaningful failure domains. Longhorn is simpler but likewise derives
availability from replicas on separate hosts; on one Proxmox server it adds
write amplification and operational complexity without physical HA.

Use CloudNativePG with the Barman Cloud plugin for PostgreSQL base backups,
continuous WAL archiving, and point-in-time recovery. See the [CloudNativePG
Barman plugin](https://cloudnative-pg.io/plugin-barman-cloud/docs/intro/).

Recovery remains layered:

- Git, OpenTofu, Talos machine configuration, Helm, and Kustomize for desired state.
- Talos etcd snapshots for Kubernetes control-plane recovery.
- Velero later for Kubernetes resources and supported CSI snapshots.
- CloudNativePG application-native database backup and restore.
- NAS mirroring into versioned S3 for allowlisted files.
- Regular disposable-environment restore tests.

GitOps is not a backup, a Proxmox snapshot is not disaster recovery, and copying
live database files is not a valid database backup.

### Developer platforms

Backstage is the mainstream open-source developer portal for catalogs,
ownership metadata, templates, documentation, and plugin aggregation. It is
valuable once the service catalog and repeatable templates solve a genuine
developer workflow. For one operator and a small application portfolio, it can
become a platform project with little immediate return. See the [Backstage
software catalog](https://backstage.io/docs/features/software-catalog/).

Crossplane is a strong option for building Kubernetes-style self-service APIs
that manage external infrastructure. Retain OpenTofu as this repository's AWS
account foundation. Adopt Crossplane only when a concrete self-service API or
composition is required. See [What is
Crossplane](https://docs.crossplane.io/latest/whats-crossplane/).

## Practitioner patterns from Reddit

Recent r/kubernetes, r/homelab, and r/selfhosted discussions repeatedly show
the following serious-homelab pattern:

- Talos or k3s, commonly running in Proxmox VMs or on mini PCs.
- Argo CD or Flux with Helm, Kustomize, and Renovate.
- Cilium or Calico, MetalLB, cert-manager, and external-dns.
- CloudNativePG for PostgreSQL.
- Prometheus, Grafana, and Loki or a VictoriaMetrics-based stack.
- Longhorn for convenience or Rook/Ceph for larger, independent-node labs.
- A separate NAS or storage server for bulk and media data.

Representative discussions include:

- [October 2025 homelab stack inventory](https://www.reddit.com/r/kubernetes/comments/1o1dtky/homelab_setup_whats_your_stack/)
- [April 2026 real-world homelab stacks](https://www.reddit.com/r/kubernetes/comments/1scbsox/what_does_your_stack_look_like_sharing_my/)
- [GitOps-driven Proxmox and Talos homelab](https://www.reddit.com/r/kubernetes/comments/1lcdefa/)
- [OpenShift versus Kubernetes discussion](https://www.reddit.com/r/kubernetes/comments/1j8h7xs/difference_between_k8s_and_openshift/)
- [OpenShift versus Rancher enterprise support discussion](https://www.reddit.com/r/kubernetes/comments/1qjhowq/redhat_openshift_vs_suse_rancher_enterprise/)
- [Why people build Kubernetes homelabs](https://www.reddit.com/r/homelab/comments/1sxtqg2/why_do_people_build_kubernetes_homelabs_is_it/)

Recurring qualitative conclusions are:

- Talos is favored for dedicated Kubernetes appliances and immutable
  operations.
- k3s is favored for quick starts, smaller nodes, and familiar Linux hosts.
- Argo CD is favored for UI and application visibility; Flux is favored for a
  lighter, modular, set-and-reconcile experience.
- OpenShift is uncommon in homelabs except for explicit enterprise learning.
- Kubernetes is often unnecessary for a few static containers that Compose or
  systemd can operate more simply.
- Distributed storage on weak networks or a single physical failure domain
  generates disproportionate complexity.
- Uncontrolled operator and CRD growth can make etcd and upgrades harder to
  reason about.

These are anecdotes and repeated practitioner preferences. They should inform
usability and operational-cost decisions, but official lifecycle documents,
support matrices, and restore tests remain the evidence for production claims.

## Recommended stack for this repository

### Install or complete first

- Talos.
- Argo CD, Kustomize, Helm, and Renovate.
- Cilium and Hubble.
- Gateway API through one selected implementation.
- MetalLB and cert-manager.
- Authentik, Kubernetes RBAC, and offline break-glass access.
- Pod Security Admission and Kyverno.
- External Secrets Operator and AWS Secrets Manager through IAM Roles
  Anywhere.
- Prometheus, Alertmanager, Grafana, Loki, and Alloy or OpenTelemetry
  Collector.
- NFS CSI with the external NAS.
- CloudNativePG and the Barman Cloud plugin.
- Trivy CI, Cosign, SBOMs, and Kyverno image verification.

### Add after the baseline is stable

- Tempo and application tracing.
- Tetragon in observation mode.
- OpenCost.
- KEDA.
- VPA recommendations.
- Argo Rollouts for one suitable demonstration service.
- Velero after a restore proof.
- Backstage when catalog and scaffolding workflows justify it.
- DRA and Kueue experiments for real GPU or batch workloads.

### Defer until a concrete requirement exists

- OpenShift or OKD as the primary cluster.
- Rancher for a single cluster.
- Crossplane.
- SPIFFE and SPIRE.
- A second service mesh, policy engine, GitOps controller, or observability
  stack.
- Rook/Ceph or Longhorn on one physical Proxmox failure domain.
- Cluster Autoscaler or Karpenter without an elastic node pool.

## Decision summary

The production-like outcome comes from operational properties, not the number
of installed products:

- Reproducible builds and cluster recovery.
- Controlled upgrades and rollback.
- Least-privilege identity and short-lived credentials.
- Default-deny boundaries and admission policy.
- Observable services with actionable email alerts.
- Signed and verified software artifacts.
- Explicit data ownership and tested restores.
- A platform small enough for one operator to understand during an outage.

The existing Talos, Proxmox, separate-NAS, GitOps, Authentik, OpenFGA, Kyverno,
Roles Anywhere, and Grafana architecture satisfies this direction. Its next
step is disciplined implementation and recovery testing, not replacement with
OpenShift.

## Primary references

- [CNCF 2025 Annual Cloud Native Survey](https://www.cncf.io/announcements/2026/01/20/kubernetes-established-as-the-de-facto-operating-system-for-ai-as-production-use-hits-82-in-2025-cncf-annual-cloud-native-survey/)
- [Kubernetes production environment](https://kubernetes.io/docs/setup/production-environment/)
- [Kubernetes 1.36 release](https://kubernetes.io/blog/2026/04/22/kubernetes-v1-36-release/)
- [Gateway API](https://gateway-api.sigs.k8s.io/docs/introduction/)
- [OpenShift architecture](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/html/architecture/architecture)
- [RKE2](https://docs.rke2.io/)
- [Talos Linux](https://github.com/siderolabs/talos)
- [Cilium Hubble](https://docs.cilium.io/en/stable/observability/hubble/)
- [Kyverno](https://www.cncf.io/projects/kyverno/)
- [External Secrets Operator](https://external-secrets.io/)
- [OpenTelemetry on Kubernetes](https://opentelemetry.io/docs/platforms/kubernetes/)
- [CloudNativePG Barman plugin](https://cloudnative-pg.io/plugin-barman-cloud/docs/intro/)
- [Backstage](https://backstage.io/docs/features/software-catalog/)
- [Crossplane](https://docs.crossplane.io/latest/whats-crossplane/)
