# Feature Specification: Safe Service Vending

**Feature Branch**: `agent/aws-account-kubernetes-vending`
**Created**: 2026-08-16
**Status**: Implemented with live rollout deferred
**Input**: Retrofit PR #30 with an auditable intent and evidence layer for the existing service-vending implementation.

## Context

This specification records the intended behavior of implementation that already existed
when Spec Kit was introduced. It does not claim that PR #30 was developed prospectively
from these artifacts. Repository evidence can demonstrate deterministic behavior; only
separate operator records can demonstrate a live mutation.

## User Scenarios and Testing

### User Story 1 - Declare a service safely (Priority: P1)

A platform maintainer declares service, account, repository, Kubernetes, and optional
external-provider intent once and receives deterministic validation before any mutation.

**Independent Test**: Render the catalog twice, validate it against the schema and a
previous revision, and confirm byte-identical output plus rejection of duplicate,
capacity-exceeding, identity-changing, and invalid-lifecycle declarations.

**Acceptance Scenarios**:

1. **Given** a valid service manifest, **When** validation and rendering run, **Then** one deterministic v2 catalog is produced without credentials or network mutation.
2. **Given** an activated immutable identity changes, **When** previous-version validation runs, **Then** validation fails before a plan or apply.
3. **Given** requested Kubernetes quotas exceed cluster capacity, **When** the merged catalog is validated, **Then** the entire change fails closed.

### User Story 2 - Vend AWS and repository foundations through bounded authority (Priority: P1)

An operator can plan independently recoverable AWS organization, account, access,
security, bootstrap, repository, and module-distribution roots, while live apply remains
restricted to protected environments or a local GitHub App boundary.

**Independent Test**: Initialize and validate each OpenTofu root with non-secret example
inputs, inspect plans, and confirm CI plan roles cannot alter their own trust or apply.

**Acceptance Scenarios**:

1. **Given** a pull request, **When** organization and service workflows run, **Then** they validate or plan without creating an account or repository.
2. **Given** an interrupted account creation, **When** the recovery guide is followed, **Then** the exact account is imported into the original state key instead of retried under a new identity.
3. **Given** a repository-vending run, **When** the local wrapper starts, **Then** the App private key is removed before the short-lived token reaches OpenTofu.

### User Story 3 - Reconcile a tenant without weakening the cluster (Priority: P1)

A cluster operator can render native and Argo phases from the catalog while preserving
Ansible ownership, namespace isolation, capacity limits, admission policy, and forward
lifecycle rules.

**Independent Test**: Render both phases and compare them to committed bundles; unit
tests assert namespace, RBAC, quota, policy, secret, and lifecycle boundaries.

**Acceptance Scenarios**:

1. **Given** an active service, **When** the native phase renders, **Then** namespace, quota, LimitRange, NetworkPolicy, metadata, and admission controls are present.
2. **Given** Argo CD is disabled or unavailable, **When** tenant manifests are admitted, **Then** native validation and Pod Security controls remain the fail-closed baseline.
3. **Given** a move from Kubernetes 1.36 to 1.35, **When** an operator reviews the procedure, **Then** it requires rebuild and verified restore rather than an in-place downgrade.

### User Story 4 - Isolate and recover an external service (Priority: P1)

An operator can reconcile one dedicated Supabase project per service through local,
serialized OpenTofu execution and a durable credential-free journal.

**Independent Test**: Run the fake adapter through create, no-op, suspend, archive,
purge request, and purge paths while asserting leases, checkpoints, confirmations,
redaction, backend isolation, and tombstone behavior.

**Acceptance Scenarios**:

1. **Given** a completed binding at the same catalog commit, **When** reconciliation repeats, **Then** it is a no-op.
2. **Given** two operators, **When** both claim one binding, **Then** the bounded lease serializes mutation and stale ownership cannot commit a result.
3. **Given** a purge request, **When** confirmation omits the immutable UID or exact catalog SHA, **Then** deletion is rejected.

### User Story 5 - Audit intent, implementation, and remaining rollout (Priority: P2)

A reviewer can trace each requirement to source, tests, a commit, or an explicit deferred
gate, and can reproduce local repository-intelligence evidence without changing source.

**Independent Test**: Run the Spec Kit audit, RepoWise risk/context queries, Graphify
health and impact checks, and the golden-template contract test from a clean checkout.

**Acceptance Scenarios**:

1. **Given** an incomplete or deferred task, **When** CI audits the feature, **Then** a reason, gate, and evidence reference are mandatory.
2. **Given** a newly vended service repository, **When** its contract check runs, **Then** the pinned Spec Kit scaffold, concrete constitution, overrides, and local tooling policy are present.
3. **Given** a repository map, **When** the implementation advances without refreshing it, **Then** CI reports its analyzed parent commit as stale.

### Edge Cases

- A first catalog activation has no previous catalog; validation still checks schema, uniqueness, and capacity.
- A provider succeeds after the local process times out; the operator inspects the journal and provider identity before any retry.
- A Free Supabase project pauses for inactivity; archive is retention intent, not a backup or RPO promise.
- A Kubernetes add-on is unavailable; native admission and tenant isolation remain active.
- A generated index is stale or unhealthy; its output is labeled advisory and is not used as authority.
- A task is intentionally not run live; it remains deferred and cannot be represented by a checked static-validation task.

## Requirements

### Functional Requirements

- **FR-001**: The repository MUST normalize supported manifest versions into one deterministic catalog and validate schema, uniqueness, capacity, lifecycle, and previous-version immutability.
- **FR-002**: Activated catalog UID, service ID, repository identity, AWS account identity, Kubernetes identity, external-provider identity, and state keys MUST not be reused or silently changed.
- **FR-003**: AWS organization, account creation, access, security, bootstrap, repository, module distribution, and workload resources MUST use independently recoverable OpenTofu state boundaries.
- **FR-004**: Account retirement MUST preserve the catalog record and MUST NOT automate AWS account closure.
- **FR-005**: Repository mutation MUST run locally through a GitHub App token wrapper; pull-request CI MUST NOT receive the App private key or perform repository creation.
- **FR-006**: Newly vended repositories MUST contain the pinned Spec Kit scaffold, a concrete service constitution, local safety overrides, canonical agent wrappers, and a deterministic repository-contract test.
- **FR-007**: Kubernetes rendering MUST enforce the documented Ansible, Helmfile, and Argo CD ownership split plus namespace, quota, network, admission, Pod Security, and RBAC controls.
- **FR-008**: A Kubernetes minor-version decrease MUST be treated as rebuild and verified restore, never as an in-place `kubeadm upgrade` or package downgrade.
- **FR-009**: Argo CD and Kyverno MUST stay disabled until compatibility, backup, restore, health, policy, and rollback gates have operator evidence.
- **FR-010**: Supabase v1 MUST use one dedicated project per service with public signup, Storage, agent row access, shared Auth, and backup promises out of scope.
- **FR-011**: External-provider reconciliation MUST be local, serialized, idempotent, checkpointed, state-isolated, and journaled without credentials.
- **FR-012**: Purge MUST require a forward lifecycle request plus confirmation containing the immutable service UID and exact catalog commit; tombstones MUST remain.
- **FR-013**: Secret material MUST resolve only at runtime, avoid arguments and repository files, and be removed from parent environments before child tools execute.
- **FR-014**: Destructive, billable, external, booking, account, repository, Kubernetes, and add-on mutations MUST default disabled and require explicit reviewed evidence.
- **FR-015**: Agent access MUST default to AWS read-only with explicit secret/decrypt denies and no external-service data-plane access.
- **FR-016**: Recovery documentation MUST cover interrupted AWS account creation, external-provider reconciliation, Kubernetes rebuild/restore, Supabase pause/restore, purge, and application cutover rollback.
- **FR-017**: CI MUST reject unresolved Spec Kit placeholders, evidence-free tasks, unexplained deferred states, stale repository maps, invalid pins, and missing golden-template scaffolding.
- **FR-018**: RepoWise MUST be the primary ignored local index; Graphify MUST be limited to reviewed high-risk snapshots; neither may install automatic hooks or receive credentials.
- **FR-019**: OpenAPI contracts MUST live under `contracts/openapi/`, while root `specs/` remains exclusively numbered Spec Kit feature intent.
- **FR-020**: Stable module interfaces and architecture MUST be available as generated terraform-docs tables and reviewed Mermaid diagrams.

### Safety and Authority Requirements

- **SR-001**: Every managed resource MUST have exactly one declared control-plane and state owner.
- **SR-002**: No secret value may enter source, logs, diffs, process arguments, generated intelligence, or agent context.
- **SR-003**: Immutable identity and lifecycle validation MUST happen before any mutation boundary.
- **SR-004**: All live and irreversible gates MUST fail closed and cite evidence rather than infer completion.
- **SR-005**: Every mutation path MUST define idempotency, checkpoints, retry ownership, and recovery.
- **SR-006**: Static tests and generated analysis MUST never be presented as proof that a live operation occurred.

### Key Entities

- **Service declaration**: Human-authored desired state with immutable UID and service identity.
- **Rendered catalog**: Deterministic normalized authority consumed by all reconcilers.
- **Binding**: One service-to-account, cluster, repository, or external-provider relationship.
- **Journal record**: Credential-free operation, lease, checkpoint, outcome, and catalog-SHA evidence.
- **Rollout gate**: Disabled-by-default assertion whose activation requires reviewed evidence.
- **Repository snapshot**: Advisory graph generated for one implementation commit and reviewed before publication.

## Non-Goals

- Running a live Kubernetes downgrade or rebuilding the homelab cluster in this PR.
- Applying AWS organization or account OpenTofu, creating or closing an AWS account, or vending a live repository.
- Creating, restoring, or purging a hosted Supabase project.
- Retrieving or inspecting any secret, credential, API key, token, or password.
- Shared Supabase projects, shared Auth, custom Auth gateways, Storage, public signup, custom SMTP, or agent database access.
- Automatically enabling Argo CD, Kyverno, GuardDuty, booking, account vending, provider adapters, or external-service gates.
- Adopting Backstage, hosted code-index services, or unsource-reviewed community Spec Kit extensions.

## Live-Mutation Disclosure

- **Performed**: No live infrastructure or secret operation was performed while implementing or validating this feature.
- **Not performed**: No Kubernetes downgrade/rebuild, Ansible tenant apply, AWS plan/apply with live credentials, AWS account vend/closure, GitHub repository vend, Supabase project create/restore/purge, hosted auth canary, or secret retrieval occurred.
- **Rollout gates**: All newly introduced live service, adapter, add-on, account, repository, and booking gates remain disabled until their documented evidence is produced by an authorized operator.

## Success Criteria

- **SC-001**: Two consecutive catalog renders are byte-identical and all catalog unit tests pass.
- **SC-002**: Every FR and SR maps to at least one task and concrete evidence or an explicit deferred gate.
- **SC-003**: The Spec Kit audit reports zero unresolved placeholders, missing evidence references, unexplained deferred tasks, or missing template files.
- **SC-004**: SDK generation, Spectral lint, and API documentation staging use only `contracts/openapi/` as source.
- **SC-005**: The golden template validates itself and contains the same v0.16.4 managed scaffold and safety overrides as root.
- **SC-006**: RepoWise records the indexed commit and returns overview, change-risk, and targeted context/risk without source mutation.
- **SC-007**: Graphify reports graph-health and PR impact, and the committed review map identifies versions, input commit, communities, critical paths, and reviewed inferred edges.
- **SC-008**: Relevant unit, Ansible syntax, OpenTofu validation, lint, formatting, and security suites pass without live credentials.

## Assumptions

- PR #30 remains draft until the retrofit, evidence, and validation results are reviewed.
- Existing implementation commit `20e1672` is the point-in-time implementation baseline.
- OpenTofu remains the IaC tool and existing authority boundaries are not migrated.
- User-local MCP registration is permitted, but project and editor configuration mutation is not.
