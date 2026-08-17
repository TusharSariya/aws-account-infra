# Research: Safe Service Vending

## Kubernetes downgrade and restore

**Decision**: Do not perform an in-place Kubernetes minor downgrade. Rebuild the control
plane from the pinned 1.35 configuration and restore verified etcd plus application data.

**Rationale**: Kubernetes documents `kubeadm upgrade` as a forward upgrade workflow,
enforces version-skew rules, and does not support skipped minor upgrades or general
reconfiguration. No supported downgrade procedure was identified. Rebuild/restore keeps
the recovery boundary explicit.

**Source**: [Kubernetes kubeadm upgrade documentation](https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-upgrade/)

**Rejected**: Package pinning plus `kubeadm upgrade apply` to an older minor. It would
mistake package installation for a supported control-plane/data downgrade.

## Argo CD and Kyverno compatibility

**Decision**: Pin Argo CD application 3.5.1/chart 10.3.3 and Kyverno application
1.18.2/chart 3.8.2, but leave both disabled until restore and platform gates pass.

**Rationale**: Argo CD 3.5 lists Kubernetes 1.35 in its tested range. Kyverno 1.18 lists
Kubernetes 1.33 through 1.35 as supported. Compatibility removes one uncertainty but does
not prove this cluster's backup, policy, capacity, or rollback readiness.

**Sources**: [Argo CD tested Kubernetes versions](https://argo-cd.readthedocs.io/en/release-3.5/operator-manual/tested-kubernetes-versions/), [Kyverno releases and compatibility](https://kyverno.io/docs/installation/releases/)

**Rejected**: Enabling add-ons based only on version tables. Native admission and Pod
Security provide a safer baseline until live evidence exists.

## Supabase isolation and recovery limits

**Decision**: Use one dedicated project per service, disable public signup and Storage,
promise no Free-plan backup/RPO, and keep archive distinct from recoverability.

**Rationale**: Supabase describes each project as a dedicated instance. Free projects may
pause after low activity, have a limited dashboard restore window, have a two-active-
project quota, and do not include downloadable automatic backups. Paid-plan backup and
PITR properties cannot be assumed for a Free project.

**Sources**: [Supabase billing FAQ](https://supabase.com/docs/guides/platform/billing-faq), [Free project pausing](https://supabase.com/docs/guides/platform/free-project-pausing), [Database backups](https://supabase.com/docs/guides/platform/backups)

**Rejected**: Shared Auth or a shared project. It couples lifecycle, data access, quotas,
and blast radius across services.

## Specification tooling

**Decision**: Pin Spec Kit v0.16.4 with Codex skills and shell scripts. Use the core
workflow and project-local template overrides; disable community extensions.

**Rationale**: Managed manifests make the upstream scaffold auditable while the override
stack adds repository policy without editing managed core templates. The already-written
implementation is labeled retrospective rather than rewritten as prospective history.

**Rejected**: Keeping `product/` or copying OpenAPI under `specs/`. Both create competing
layout meanings. Community extensions remain disabled until independently reviewed.

## Repository understanding

**Decision**: RepoWise v0.43.0 is the primary local MCP/index; Graphify v0.9.45 with only
Terraform and MCP extras is a high-risk PR snapshot tool.

**Rationale**: RepoWise provides Terraform structure, git co-change, health, dead-code,
change-risk, and freshness metadata from one ignored local index. Graphify adds reviewed
community and dependency-path evidence without becoming a second maintained index.

**Rejected**: RepoWise `init --dry-run` as a read-only check because v0.43.0 was observed
persisting an index. Also rejected automatic hooks, editor mutation, saved keys, hosted
indexes, and committing raw graph output.

## Human-readable architecture

**Decision**: Pin terraform-docs v0.24.0 for module tables and keep stable flow diagrams
in Mermaid inside reviewed Markdown.

**Rationale**: Module interfaces can be regenerated deterministically from HCL, while
Mermaid remains diffable and accessible without a portal. Backstage and heavier hosted
documentation/index products are deferred until repository count justifies operation.
