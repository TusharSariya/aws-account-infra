# Security Checklist: Safe Service Vending

**Purpose**: Review authority, secret, identity, lifecycle, and recovery requirements
**Created**: 2026-08-16
**Feature**: [`../spec.md`](../spec.md)

## Authority and infrastructure

- [x] CHK001 Each AWS, Kubernetes, GitHub, Supabase, specification, and intelligence resource has one owner.
- [x] CHK002 Pull-request workflows validate/plan and do not receive live provider or secret authority.
- [x] CHK003 State roots isolate management, account, workload, repository, and external-provider recovery.
- [x] CHK004 Agent defaults explicitly deny secret values, parameter values, decryption, and database rows.

## Secret handling

- [x] CHK005 Secrets resolve only at runtime using approved dynamic references.
- [x] CHK006 Private keys, tokens, passwords, and response bodies are absent from arguments, logs, diffs, temporary repository files, and generated intelligence.
- [x] CHK007 Sensitive provider state is treated as credential-equivalent and isolated from ordinary read-only access.
- [x] CHK008 Rotation responsibilities and credential-removal boundaries are documented.

## Identity, lifecycle, and recovery

- [x] CHK009 Immutable service, account, repository, cluster, provider, binding, and state identities are named.
- [x] CHK010 Lifecycles are forward-only with explicit recovery overrides and permanent tombstones.
- [x] CHK011 Purge confirmation binds immutable UID to exact catalog commit.
- [x] CHK012 Account-create, provider-timeout, cluster rebuild, pause/restore, purge, and cutover recovery paths are documented.

## Rollout and disclosure

- [x] CHK013 Destructive, billable, and external gates default disabled and require named evidence.
- [x] CHK014 Static tests cannot be mistaken for evidence of a live mutation.
- [x] CHK015 No live AWS, Kubernetes, GitHub, Supabase, hosted canary, or secret operation is claimed.
- [x] CHK016 Deferred live work remains visible with its enabling authority and gate.
