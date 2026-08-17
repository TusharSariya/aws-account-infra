# Vended Service Constitution

## Core Principles

### I. Specification Is the Intent Authority

Every feature MUST begin with a numbered root-level `specs/` artifact that defines user
outcomes, acceptance scenarios, non-goals, and measurable success. Implementation tasks
MUST trace to requirements and name their file and test evidence.

### II. Declarative Infrastructure Ownership

Infrastructure MUST be declarative, reviewable, and owned by one documented control
plane. Pull-request workflows MUST validate and plan only; live cloud, cluster, database,
and repository mutations require a protected operator or deployment boundary.

### III. Secret Non-Disclosure and Least Authority

Credentials MUST never be printed, committed, logged, diffed, stored in generated agent
artifacts, or passed in process arguments. Values MUST resolve at runtime through the
approved secret mechanism. Agents and services MUST receive no data-plane access by
default, and every exception MUST be explicit, minimal, and revocable.

### IV. Immutable Identity and Safe Lifecycle

Service UIDs, repository identities, environment identities, provider identifiers, and
state locations MUST be immutable after activation. Lifecycle transitions MUST be
forward-only unless a documented recovery process authorizes reversal. Destructive and
billable capabilities MUST remain behind disabled, evidence-backed rollout gates.

### V. Recovery and Verification

Features MUST document idempotency, checkpoints, rollback or recovery, and failure
handling. Relevant unit, integration, contract, security, and infrastructure checks MUST
pass before merge. Deferred work MUST stay explicit with an owner or enabling condition.

## Service Requirements

Specifications and plans MUST identify IaC ownership, secret materialization, recovery,
immutable identities, rollout gates, and whether any live mutation occurred. Generated
analysis is advisory evidence; committed specifications, contracts, migrations, source,
and tests remain authoritative.

## Delivery Workflow

Reviewers MUST verify requirement-to-task evidence, test results, and the absence of
unresolved placeholders. Live changes happen only through approved environments or local
operator procedures. Repository analysis tools MUST not modify tracked source or create
unapproved project configuration.

## Governance

This constitution supersedes conflicting local practice. Amendments require rationale,
migration impact, and semantic versioning. Every feature plan and review MUST record a
constitution check or an explicit, approved exception.

**Version**: 1.0.0 | **Ratified**: 2026-08-16 | **Last Amended**: 2026-08-16
