# AWS Account Infrastructure Constitution

## Core Principles

### I. Declarative Ownership

Every managed resource MUST have one documented authority. AWS and external-provider
infrastructure MUST remain in OpenTofu, Kubernetes platform and tenant resources MUST
remain in their documented Ansible, Helmfile, or Argo CD boundary, and imperative tools
MUST reconcile only the resources explicitly assigned to them. A change MUST identify
the owning root, state, and recovery path before implementation.

### II. Least Authority and Secret Non-Disclosure

Pull-request validation MUST be non-mutating and credential-free. Live operations MUST
use the narrowest protected role or local operator boundary available. Secret values MUST
never be printed, committed, diffed, logged, written to temporary repository files, or
passed in process arguments. Secrets Manager values MUST resolve only at runtime through
`asm-exec` dynamic references.

### III. Immutable Identity and Forward Lifecycle

Catalog UIDs, service IDs, repository identities, provisioned account identities,
provider-assigned identifiers, and state keys MUST be immutable after activation.
Lifecycle transitions MUST be monotonic unless a documented, operator-approved recovery
path explicitly permits reversal. Purged identities and tombstones MUST never be reused.

### IV. Fail-Closed Rollout Gates

Destructive, billable, or externally mutating behavior MUST default to disabled. A gate
MUST cite reviewed evidence and MUST NOT infer success from intent, configuration, or a
passing static test. Bypasses MUST be narrow, explicit, and unable to bypass secret,
state, or irreversible-lifecycle protections.

### V. Testable Recovery and Evidence

Every feature MUST define failure boundaries, idempotency behavior, checkpoints, and a
recovery or rollback procedure. Tasks MUST link requirements to concrete files, tests,
or commits. Deferred, partial, and blocked work MUST remain visible with a reason and an
enabling condition; documentation MUST NOT claim that a live action occurred without
recorded evidence.

## Infrastructure and Repository Requirements

Specifications MUST record IaC ownership, authority boundaries, secret handling,
immutable identities, lifecycle transitions, rollout gates, live-mutation disclosure,
and recovery behavior. Stable architecture belongs in reviewed Markdown and Mermaid.
Generated repository intelligence is supplementary evidence and never overrides source,
schemas, tests, state, or this constitution.

## Delivery and Review Gates

Changes MUST pass the relevant deterministic unit, schema, formatting, security, and IaC
validation suites. Live AWS applies, account vending, Kubernetes reconciliation,
external-provider mutations, repository creation, and secret retrieval require explicit
operator authorization outside ordinary pull-request validation. Reviewers MUST verify
that generated evidence names its tool version and analyzed commit.

## Governance

This constitution governs Spec Kit artifacts and implementation reviews. Amendments
require an explicit pull request, rationale, migration impact, and version change using
semantic versioning. Compliance is reviewed in planning and again before merge; an
exception must be time-bounded, documented, and owned.

**Version**: 1.0.0 | **Ratified**: 2026-08-16 | **Last Amended**: 2026-08-16
