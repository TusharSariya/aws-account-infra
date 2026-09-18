# Production-Like Talos Homelab Platform Roadmap

## Status

Proposed roadmap. This document does not authorize deployment or live
infrastructure changes. Every component version and compatibility claim must be
revalidated against official documentation before apply.

## Summary

Build a feature-rich platform-engineering lab with selected personal-cloud
applications while recognizing that one Proxmox server remains a single
physical failure domain.

Preserve the repository's existing architecture:

- Proxmox hosts two Talos VMs: a 2-vCPU/4-GiB control plane and a 38-vCPU/172-GiB shared worker with worker-local persistent storage. The dedicated NAS and sandbox VMs were removed by the approved 2026-09-12 revision.
- Tailscale runs directly on Proxmox for private remote administration independent of Kubernetes; package source, enrollment, enabled service and off-home authenticated HTTPS/SSH are verified (OpenSpec task 2.9). Fresh-machine recovery remains pending.
- Talos machine configuration and Helm bootstrap cluster-critical add-ons.
- Argo CD reconciles allowlisted applications, not its own dependencies.
- Helm packages third-party software; Kustomize manages first-party bases and
  overlays.
- AWS Secrets Manager is the secret source of truth, accessed through
  workload-specific IAM Roles Anywhere identities.
- Authentik authenticates humans; Kubernetes RBAC authorizes cluster access;
  OpenFGA authorizes broker-managed resources.
- Cloudflare Tunnel exposes explicitly approved applications without router
  port forwarding.
- Alertmanager provides plugin-style alert routing, with email as the only
  initially enabled receiver.

The repository already contains Cilium, MetalLB, Istio Gateway API,
metrics-server, GPU Operator, kube-prometheus-stack, Loki, and Pi-hole. It also
contains definitions or plans for cert-manager, KEDA, Argo CD, and Kyverno.
Complete and harden these choices instead of installing competing systems.

This roadmap is the sequencing and decision layer. Detailed implementation
records remain in:

- [Practical Kubernetes security hardening for 2026](kubernetes-security-hardening-2026.md)
- [Additional Kubernetes tooling for 2026](kubernetes-additional-tools-2026.md)
- [Seven-day WAN partition resilience](network-partition-resilience.md)
- [Kubernetes tooling landscape for 2026](kubernetes-tooling-landscape-2026.md)
- [Talos Kubernetes rebuild](talos-kubernetes-rebuild.md)
- [Authorized agent NAS](authorized-agent-nas.md)
- [Kubernetes observability](../observability.md)
- [Gateway API](../gateway-api.md)
- [cert-manager](cert-manager.md)
- [KEDA](keda.md)

## Target platform

### Delivery and configuration

- Keep Talos, Cilium, storage, Gateway API, Istio, cert-manager, observability,
  Kyverno, External Secrets Operator, and Argo CD bootstrap under pinned Helm
  releases.
- Run non-HA Argo CD because HA mode requires independent nodes and cannot
  protect against loss of the shared Proxmox host. Argo manages only application
  namespaces through restricted `AppProject` resources. See [Argo CD HA
  guidance](https://argo-cd.readthedocs.io/en/stable/operator-manual/high_availability/).
- Start Argo applications with manual sync. Progress to automated sync and
  self-healing after policy and restore tests pass. Enable pruning per
  application with `allowEmpty: false` and confirmation for protected
  resources.
- Use Argo sync waves for database migrations and ordered dependencies. See
  [Argo CD sync waves](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-waves/).
- Use Kustomize for first-party application bases and environment overlays. Use
  pinned Helm charts for external applications. Do not nest several Helm and
  Kustomize templating layers.
- Add Renovate to propose chart, container, GitHub Actions, OpenTofu, and
  manifest version updates. Never auto-merge Kubernetes, Talos, CNI, storage,
  Gateway, or admission-controller upgrades.
- Keep GitHub Actions as CI. Do not add Tekton or an in-cluster registry while
  GitHub Actions and ECR or GHCR meet those needs.
- Later, add Argo Rollouts for one multi-replica demonstration service and
  ApplicationSet-generated preview namespaces. Do not use rollouts for
  singleton stateful applications.

### Networking, ingress, and exposure

- Keep Cilium in the selected VXLAN and kube-proxy configuration, MetalLB for
  LAN addresses, and Istio as the only Gateway API implementation.
- Enable Hubble Relay and UI after default-deny network policies are
  established, providing visibility into allowed and denied flows.
- Complete cert-manager DNS-01 issuance and HTTPS on the Istio Gateway. Keep
  public and internal certificate responsibilities separate.
- Deploy `cloudflared` through Helmfile after External Secrets and Authentik are
  operational. Use an outbound-only Cloudflare Tunnel with explicit hostname
  routes and a terminal `404` rule. See [Cloudflare's Kubernetes tunnel
  guidance](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/deployment-guides/kubernetes/).
- Manage Cloudflare DNS and tunnel routes declaratively through OpenTofu.
  Continue managing split-horizon LAN records through the existing Pi-hole and
  Helm bootstrap path. Do not add ExternalDNS initially.
- Use Cloudflare Access backed by Authentik for approved private applications
  that must be reachable from the internet. Public APIs require application
  authentication, rate limiting, explicit NetworkPolicy, and monitoring.
- Keep the Kubernetes API, Talos API, Argo CD, Grafana, Prometheus, OpenFGA,
  databases, NAS administration, and Authentik administration restricted to
  the LAN or tailnet.
- Do not expose a wildcard route from Cloudflare to Istio. Every public
  hostname must be catalog-declared and individually approved.

### Host-level Tailscale administration

The operator reports Tailscale installed directly on `pve` on 2026-09-12. Treat installation as reported evidence, not proof of enrollment, remote reachability or route approval. Record the installed version, package source, service persistence, tailnet identity and non-secret connection settings during verification.

Use Tailscale on the Proxmox host for private UI (HTTPS 8006) and ordinary SSH (TCP 22) from authorized administrator devices. Keep Proxmox authentication and SSH keys; Tailscale SSH is a separate optional feature, not implied by installing the client. Preserve trusted TLS verification for automation and document the certificate trust path. Do not expose administration through public port forwarding, Cloudflare Tunnel or Tailscale Funnel.

Plan Proxmox as the subnet router for the four host routes `10.0.0.92/32`, `10.0.0.220/32`, `10.0.0.222/32`, `10.0.0.231/32` so authorized administrators can reach Talos and selected service addresses without adding Tailscale to every Talos VM. Subnet-route advertisement, tailnet route approval, client route acceptance, forwarding and the operator-approved access policy must be recorded and verified before this path is accepted. No route advertisement or firewall change is inferred from the installation. Review default subnet SNAT and return paths explicitly; management access is not proof that an external GPU worker has the bidirectional node/Cilium connectivity it needs.

Proxmox connects directly to the LAN router at `10.0.0.1`; no laptop hop is required. Direct LAN SSH and the Proxmox console remain recovery fallbacks. No third VM or Kubernetes-hosted operator is needed for host recovery access.

Include the package/version source, service setup, tags, tailnet grants/ACLs, approved routes, certificate handling, key-expiry policy, administrator account recovery and device re-enrollment/revocation in the DR procedure. Keep auth keys and node private state out of plaintext Git. Enrollment and recovery access must not depend solely on this Kubernetes cluster or its Authentik instance. Verify UI and SSH from a separate internet connection such as a phone hotspot, and verify local fallback without Tailscale before declaring remote recovery ready.

References: [Proxmox integration](https://tailscale.com/docs/integrations/proxmox), [subnet route acceptance](https://tailscale.com/docs/reference/route-injection), [subnet SNAT and routing](https://tailscale.com/docs/features/site-to-site).

### Identity and authorization

- Configure Authentik as the human OIDC provider with stable `sub`, a prefixed
  group claim, PKCE or device login, MFA for administrators, and 15-minute
  access tokens.
- Map Authentik groups to narrow Kubernetes RoleBindings. Preserve offline
  Talos and Kubernetes break-glass credentials because Authentik runs inside
  the environment it protects.
- Give every controller and application a dedicated ServiceAccount. Disable
  automatic service-account token mounting and explicitly project
  audience-bound tokens where required. See [Kubernetes ServiceAccount
  guidance](https://kubernetes.io/docs/concepts/security/service-accounts/).
- Use Kubernetes TokenReview for broker validation of projected service-account
  tokens.
- Keep OpenFGA private behind the workspace broker. It governs projects, runs,
  workspaces, datasets, and artifacts only. Kubernetes RBAC remains
  authoritative for Kubernetes objects.
- Keep Pod Security Admission as the cluster floor and use Kyverno for custom
  controls. Begin in Audit mode, monitor PolicyReports, remediate violations,
  and then enforce security-critical rules.
- Write new Kyverno policies using its CEL-based policy types in preparation
  for the legacy policy-type deprecation. See [Kyverno policy
  types](https://kyverno.io/docs/policy-types/overview/).
- Add Tetragon in observe-only mode after Cilium, Hubble, and baseline policies
  are stable. Do not install Falco simultaneously. Validate what Tetragon can
  observe inside gVisor before relying on it for sandbox detections.
- Defer SPIFFE/SPIRE, trust-manager, and cert-manager approver-policy until a
  concrete multi-workload certificate-distribution requirement exists.

### IAM Roles Anywhere and secrets

AWS Secrets Manager is the authoritative runtime secret store. No workload may
use a long-lived AWS access key.

Create separate IAM roles, Roles Anywhere profiles, and end-entity certificates
for:

- External Secrets Operator.
- NAS S3 mirroring and recovery.
- Talos or node ECR image pulling.
- CloudNativePG S3 backups.
- Any later AWS-integrated workload.

For External Secrets Operator:

1. Register the dedicated homelab workload CA or intermediate as a Roles
   Anywhere trust anchor.
2. Issue an ESO-specific certificate containing an exact URI SAN and rotate it
   automatically. Restrict the IAM role trust policy by trust-anchor ARN,
   source account, and certificate SAN. See the [Roles Anywhere trust
   model](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/trust-model.html).
3. Run the official, digest-pinned Roles Anywhere credential-helper image as
   an ESO sidecar using `serve`, bound only to pod loopback with
   `--hop-limit 1`.
4. Point ESO's AWS SDK at the local IMDS-compatible endpoint with
   `AWS_EC2_METADATA_SERVICE_ENDPOINT`. The helper keeps credentials in memory
   and refreshes them automatically. See the [Roles Anywhere credential
   helper](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/credential-helper.html).
5. Allow only `secretsmanager:GetSecretValue` and
   `secretsmanager:DescribeSecret` on explicit environment and namespace
   prefixes. Permit `kms:Decrypt` only on the secrets key and only through
   Secrets Manager using `kms:ViaService`. Do not grant `ListSecrets`, write,
   rotation, or deletion permissions.
6. Use namespace-scoped `SecretStore` resources and explicit
   `ExternalSecret.remoteRef` keys. Do not offer an unrestricted cluster-wide
   store.
7. Alert on failed synchronization, stale values, certificate expiry, and
   Roles Anywhere refresh failures.

Bootstrap the dedicated Roles Anywhere intermediate and ESO certificate through
the repository's secret-safe operator workflow. Any implementation involving a
live certificate, private key, password, token, or secret must first load the
required `aws-secrets-manager` skill and use `asm-exec` runtime resolution.
No secret value may enter Git, Terraform output, process arguments, logs,
diffs, or agent context.

External Secrets mirrors values into ordinary Kubernetes Secrets. Therefore,
Talos etcd encryption, RBAC, backup protection, and application reload behavior
remain required. Rotation must cover provider update, ESO refresh, projected
volume reload or controlled rollout, old-credential revocation, and alerting.

## Observability and alerts

### Signal stack

Retain and expand the Grafana stack:

- Prometheus Operator, Prometheus, Alertmanager, Grafana, kube-state-metrics,
  and node exporter.
- Grafana Alloy as a DaemonSet for structured Kubernetes logs, events, and
  later OTLP signals.
- Single-binary Loki with 7 to 14 days of retention.
- Blackbox Exporter for DNS, HTTPS, TCP, certificate, and client-path probes.
- Hubble for Cilium flow visibility.
- OpenCost for namespace allocation, request efficiency, idle capacity, and
  custom on-prem electricity and storage rates.
- VPA in recommendation-only mode. Do not permit automatic eviction initially.
- Add single-binary Tempo only when the workspace broker or another
  multi-service request path is instrumented.
- Defer Pyroscope until metrics or traces identify a profiling need.
- Keep Prometheus TSDB on local POSIX storage, never NFS. See [Prometheus
  storage guidance](https://prometheus.io/docs/prometheus/latest/storage/).
- Do not add Mimir, Thanos, Elasticsearch, or OpenSearch at this scale.

Starting observability budget:

| Resource | Reservation | Maximum or headroom |
|---|---:|---:|
| CPU | Approximately 3 vCPU | 6 vCPU |
| RAM | Approximately 8 GiB | 12 to 16 GiB |
| Prometheus | 30 GiB local PVC | 15-day and size-bounded retention |
| Loki | 30 GiB local PVC | 7 to 14-day retention |
| Grafana and Alertmanager | 3 GiB combined | Configuration kept in Git |

### Coverage

Monitor:

- Kubernetes API, etcd, scheduler, controller manager, CoreDNS, Cilium, Istio,
  CSI, certificates, pods, PVCs, and node health.
- Proxmox VM, node, LVM-thin, and storage state through a read-only API token.
- IPMI temperatures, fans, voltage, power, and hardware event log.
- ServeRAID and SMART state from the Proxmox host.
- NAS XFS, quotas, NFS and SMB, ACL drift, mirror freshness, restore results,
  and disk latency.
- CloudNativePG backup age, WAL archive health, and point-in-time restore tests.
- External DNS, ingress, authentication, and selected public endpoints.

### Plugin-style alert routing

- Prometheus rules emit normalized labels: `severity`, `service`, `component`,
  `environment`, and `runbook_url`.
- Alertmanager owns grouping, inhibition, silencing, routing, and receiver
  selection.
- Receiver definitions are modular configuration fragments. Enable SMTP email
  only initially. Keep ntfy, Discord, Slack, PagerDuty, and generic webhook
  receivers disabled but structurally supported.
- Store SMTP credentials in AWS Secrets Manager and materialize them through
  ESO. Store recipient addresses as environment configuration, not in alert
  rules.
- Argo CD Notifications uses the same email destination for deployment events
  without converting routine deployment events into Prometheus alerts.
- A hosted external heartbeat or dead-man service emails when etcd, NAS mirror,
  database backup, or restore-test jobs stop reporting.
- A hosted synthetic probe emails when the entire site, ISP, DNS, or cluster
  disappears. In-cluster Uptime Kuma may be added as a dashboard but never as
  the only external monitor.
- Maintain an always-firing watchdog and verify end-to-end delivery.
- Every page-worthy alert includes a runbook, owner, severity, and expected
  response. Host-down inhibition suppresses derivative pod and service alerts.

## Storage and recovery

- Use the shared worker's separate 1,200-GiB data disk for local persistent volumes. Accepted durable data requires independent, tested backups; losing the worker interrupts its storage. The former NAS/brokered-NFS design is deferred.
- Never place Prometheus TSDB or live PostgreSQL data directories on NFS.
- Deploy CloudNativePG with separate databases and roles for Authentik,
  OpenFGA, the broker, Backstage, and Paperless-ngx.
- Use the CloudNativePG Barman Cloud plugin for base backups, continuous WAL
  archiving, and point-in-time recovery to a dedicated S3 prefix. See
  [CloudNativePG backup documentation](https://cloudnative-pg.io/docs/1.28/backup/).
- Maintain three recovery layers:
  - Git, OpenTofu, Talos machine configuration, Helm, and Kustomize for desired state.
  - Automated off-cluster Talos etcd snapshots.
  - Application-native database and worker-data backups.
- Use Velero later for Kubernetes API objects and selected non-database volumes
  only after a restore proof. Do not make its privileged NFS filesystem backup
  the primary NAS or database strategy. See [Velero filesystem-backup
  limitations](https://velero.io/docs/v1.17/file-system-backup/).
- Keep observability data out of the versioned NAS recovery bucket.
- Treat Proxmox snapshots as convenient rollback points, not disaster recovery.

## Declarative interfaces

### Application exposure contract

Extend the service catalog with an explicit exposure contract:

```yaml
exposure:
  mode: private       # private, tailnet, or public
  authentication: oidc # oidc, cloudflare_access, application, or none
  hostname: example.homelab.tfdraw.dev
  data_classification: internal # public, internal, confidential, or sensitive
```

Rules:

- `private` creates only LAN split-DNS and Istio routing.
- `tailnet` creates no public DNS or Cloudflare route.
- `public` requires a declared hostname, security owner, rate-limit policy,
  synthetic probe, and reviewed authentication mode.
- `authentication: none` is allowed only with
  `data_classification: public` and an explicit review record.
- Administrative and sensitive applications cannot use public mode.

### Secret naming contract

Use stable AWS Secrets Manager names:

```text
homelab/<environment>/<namespace>/<application>/<secret-name>
```

Each `SecretStore` and IAM role is restricted to the smallest usable prefix.
Catalog and Git records contain only secret identifiers and expected keys, not
values.

### GitOps ownership contract

| Owner | Responsibility |
|---|---|
| OpenTofu | AWS, Cloudflare DNS and tunnel declarations, IAM, and S3 |
| Talos and Helm | Machine configuration, cluster bootstrap, and platform add-ons |
| Argo CD | Allowlisted application namespace resources |
| Kustomize | First-party application bases and environment overlays |
| Helm | Pinned third-party packages and reviewed values |
| Broker | Dynamic workspaces, grants, and brokered storage volumes |

Argo CD must never own its own bootstrap dependencies, Talos machine state,
NAS host configuration, or AWS identities.

## Application portfolio

### Developer platform

- Deploy Backstage privately and connect its catalog to the repository's
  existing service catalog.
- Add ApplicationSet preview namespaces with quotas, expiry, and automatic
  cleanup after baseline Argo CD operation is proven.
- Add one Argo Rollouts demonstration service with metric-based canary
  analysis.
- Optionally add ephemeral GitHub Actions runners on the sandbox worker for
  trusted repositories only. Never execute untrusted fork pull requests with
  credentials or access to internal services.
- Add Argo Workflows only when agent or data pipelines need DAG orchestration
  beyond Kubernetes Jobs and KEDA.
- Do not add Harbor, Gitea, Tekton, Crossplane, Flux, or a second service mesh
  without a new unmet requirement.

### Personal cloud

Deploy Paperless-ngx first:

- Place it behind Cloudflare Access and Authentik.
- Store documents and application exports on a quota-controlled NAS resource.
- Keep PostgreSQL on local CloudNativePG storage with S3 point-in-time recovery.
- Use a dedicated Valkey or Redis instance according to the supported
  Paperless deployment contract.
- Run OCR consumers with explicit CPU and memory limits so ingestion cannot
  starve platform services.
- Add application-native Paperless export and import verification to the
  monthly recovery test.

Later candidates:

- Immich after photo-storage and database-restore testing. Originals may use
  NAS-backed storage, but its live PostgreSQL data must remain local.
- Jellyfin for NAS media, preferably using direct play or GPU-assisted
  transcoding.
- Linkding, FreshRSS, or Mealie as lightweight applications.
- Nextcloud only if browser sync, calendars, or collaboration justify its
  overlap with SMB.
- Home Assistant as a separate Proxmox VM, not Kubernetes, for USB, mDNS, and
  maintenance independence.

## Rollout

### 1. Reconcile current truth

- Treat the Kubernetes 1.35 vending document as the legacy kubeadm current
  state and the Talos Kubernetes 1.36 design as the target. Retire the legacy
  instructions after the parallel Talos migration completes.
- Revalidate every chart and controller against the chosen Kubernetes version.
- Upgrade the Kyverno pin before Kubernetes 1.36 if its support matrix requires
  it.
- Record deployed, implemented-but-disabled, pending-apply, and planned
  components separately.

### 2. Recovery and hardware gate

- Finish ServeRAID, SMART, IPMI, UPS, thin-pool and worker-storage monitoring.
- Verify Tailscale on pve, remote UI/SSH from a phone hotspot, documented current tailnet policy, planned subnet-route behavior and local recovery fallback; preserve reproducible re-enrollment instructions.
- Back up Talos machine secrets and break-glass credentials offline.
- Automate etcd snapshots and prove bare-cluster restoration before adding
  dependencies.

### 3. Talos platform foundation

- Deploy the control plane and shared worker using the approved two-VM allocation; retain gVisor policy for sandbox pods sharing the worker.
- Reconcile CoreDNS, Cilium, metrics-server, MetalLB, Gateway API, Istio, and
  cert-manager.
- Establish default-deny network policy and HTTPS for private services.

### 4. Observability

- Reconcile kube-prometheus-stack and Loki.
- Add Alloy, Blackbox Exporter, infrastructure exporters, external probes,
  Alertmanager email, watchdog, and runbooks.
- Add Hubble and OpenCost once baseline telemetry is stable.

### 5. AWS workload identity and secrets

- Create dedicated Roles Anywhere roles, profiles, and certificate identities.
- Prove the ESO helper sidecar in a disposable namespace.
- Test credential refresh, certificate rotation, revocation, prefix isolation,
  KMS restrictions, and AWS outage behavior.
- Deploy ESO and migrate runtime secrets to AWS Secrets Manager.

### 6. Data and identity services

- Deploy CloudNativePG and prove S3 base backup, WAL archive, and point-in-time
  restore.
- Deploy Authentik, OpenFGA, and the workspace broker.
- Enable Kubernetes OIDC, MFA, scoped RBAC, service-account token controls, and
  offline break-glass access.

### 7. Policy and GitOps

- Enable Kyverno in Audit mode, remediate findings, and then enforce
  security-critical controls.
- Deploy non-HA Argo CD with restricted AppProjects and manual sync.
- Pilot one stateless application, then enable self-healing and carefully
  scoped pruning.
- Add Renovate, CI rendering and schema tests, policy tests, Trivy scanning,
  SBOM and provenance generation, Cosign signing, and Kyverno image
  verification.

### 8. Controlled public access

- Deploy Authentik's public OIDC endpoint and `cloudflared` through the explicit
  tunnel route contract.
- Prove Cloudflare Access, origin TLS, unmatched-host denial, rate limiting,
  authentication failure behavior, and external monitoring with a disposable
  application.
- Approve public exposure one catalog service at a time.

### 9. Developer and personal workloads

- Deploy Backstage privately.
- Deploy Paperless-ngx as the first personal-cloud workload.
- Add preview environments, one canary-rollout demonstration, and optional
  sandboxed Actions runners only after the platform acceptance tests pass.

## Acceptance tests

- Verify private Proxmox UI and SSH access from outside home through host-level Tailscale, scoped subnet management access when enabled, startup persistence and local fallback.
- Recover Tailscale enrollment and tailnet policy/routes without Kubernetes or cluster-hosted identity services.

- Rebuild the cluster from Git and restore etcd without Authentik, Argo CD, or
  the NAS being initially available.
- Restore CloudNativePG to a timestamp and run application-level verification
  queries.
- Restore a worker-local resource and a deleted S3 object version with checksum
  verification.
- Confirm an unapproved hostname cannot traverse Cloudflare Tunnel or attach to
  the Gateway.
- Confirm public applications enforce Cloudflare Access or application
  authentication while administrative endpoints remain private.
- Confirm Authentik outage blocks new logins but break-glass cluster
  administration still works.
- Confirm OpenFGA failure denies broker requests without affecting Kubernetes
  RBAC.
- Confirm Roles Anywhere credentials rotate automatically, certificate
  revocation blocks new sessions, and no static AWS credential exists.
- Confirm ESO cannot read secrets outside its permitted prefixes or use
  unrelated KMS keys.
- Confirm Kyverno blocks unsigned images, privileged workloads, arbitrary NAS
  paths, invalid sandbox placement, and unapproved service-account tokens.
- Confirm Argo detects drift, Git revert performs rollback, and loss of Argo
  does not stop running applications.
- Confirm external email fires for total host loss, missed backup heartbeat,
  certificate expiry, NAS mirror lag, and a synthetic public-endpoint failure.
- Confirm Paperless documents, database, configuration, and application export
  restore into a disposable namespace.
- Run monthly application restore tests and a quarterly full-cluster recovery
  exercise, recording measured RPO and RTO.

## Assumptions and explicit avoidances

- The primary goal is a platform-engineering lab with useful home services.
- Paperless-ngx is the first personal-cloud application.
- Selected public access uses Cloudflare Tunnel; the router has no public port
  forwarding.
- Alert receivers are modular, with email as the only initial destination.
- AWS Secrets Manager is accessed through IAM Roles Anywhere; long-lived AWS
  keys are prohibited.
- The platform is production-like but not physically highly available.
- Avoid Ceph, Rook, and Longhorn across VMs on one physical host.
- Avoid replicas presented as HA when they share the same host and RAID array.
- Avoid Kubernetes-hosted NFS, Prometheus on NFS, and live databases on NFS.
- Avoid Vault solely as a production checkbox when AWS Secrets Manager is
  already authoritative.
- Avoid competing GitOps, admission, Gateway, and service-mesh systems.
- Avoid Cluster Autoscaler and Karpenter because the Proxmox host has no elastic
  node pool.
- Avoid broad public exposure and publicly reachable administrative services.

## References

- [Kubernetes production environment](https://kubernetes.io/docs/setup/production-environment/)
- [Kubernetes security](https://kubernetes.io/docs/concepts/security/)
- [Kubernetes auditing](https://kubernetes.io/docs/tasks/debug/debug-cluster/audit/)
- [Talos security checklist](https://docs.siderolabs.com/talos/v1.13/security/talos-security-checklist)
- [Talos disaster recovery](https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/lifecycle-management/disaster-recovery)
- [Argo CD](https://argo-cd.readthedocs.io/en/stable/)
- [Kustomize](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/)
- [Renovate managers](https://docs.renovatebot.com/modules/manager/)
- [Cilium Hubble](https://docs.cilium.io/en/stable/observability/hubble/)
- [cert-manager Gateway support](https://cert-manager.io/docs/usage/gateway/)
- [External Secrets Operator](https://external-secrets.io/)
- [AWS IAM Roles Anywhere](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/introduction.html)
- [AWS Secrets Manager IAM policies](https://docs.aws.amazon.com/secretsmanager/latest/userguide/auth-and-access_iam-policies.html)
- [OpenFGA concepts](https://openfga.dev/docs/authorization-concepts)
- [OpenTelemetry on Kubernetes](https://opentelemetry.io/docs/platforms/kubernetes/)
- [Prometheus Operator](https://prometheus-operator.dev/)
- [Grafana Alloy](https://grafana.com/docs/alloy/latest/introduction/)
- [Grafana Loki](https://grafana.com/docs/loki/latest/)
- [OpenCost](https://opencost.io/docs/)
- [NFS CSI driver](https://github.com/kubernetes-csi/csi-driver-nfs)
- [CloudNativePG backups](https://cloudnative-pg.io/docs/1.28/backup/)
- [Paperless-ngx](https://docs.paperless-ngx.com/)

### Optional Tailscale access hardening

Operator decision: retain the supplied default allow-all tailnet network policy for the initial personal build. Tailnet membership is the accepted network trust boundary; all members/devices can reach advertised destinations broadly. This does not make Serve public. The proposed account/port-scoped policy in `config/environments/proxmox/homelab/tailscale/policy.json` is an unapplied optional improvement, including removal of Funnel permission. Revisit before adding other users or less-trusted devices. Do not block VM creation or subnet-route acceptance on adopting it. Tailnet-only management, existing host authentication and recovery prerequisites remain required.

## Approved bounded database prerequisite

The owner subsequently approved `add-apps-postgres-backups`: one PostgreSQL primary and daily versioned S3 logical backups within 2 CPU / 6 GiB on the existing worker. See [database runbook](../apps-postgres.md) and [OpenSpec change](../../openspec/changes/add-apps-postgres-backups/proposal.md), linked to roadmap #32. This does not select a first app or resume the broader resilience/WAL/HA programme. Acceptance is tracked separately from implementation.
