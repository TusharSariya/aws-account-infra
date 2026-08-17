# Data Model: Safe Service Vending

## Identity hierarchy

```text
Service (immutable uid, id)
├── Repository binding (immutable owner/name identity)
├── AWS account binding by environment (immutable key, id, name, root email)
├── Kubernetes binding by cluster (immutable ECR repository and hostname after activation)
└── External binding by provider (immutable organization, project name/ref, region)
```

The service declaration is human-authored. The rendered catalog is deterministic,
normalized v2 state. A binding ID is derived from immutable service/provider identity and
is never reused after purge.

## Lifecycle states

| Binding | States | Normal transitions | Terminal behavior |
| --- | --- | --- | --- |
| AWS account | `active`, `retired` | `active -> retired` | Catalog entry remains; closure is manual and out of scope |
| Kubernetes tenant | `active`, `suspended`, `archived` | Forward only | Namespace/data are not automatically destroyed |
| Supabase project | `active`, `suspended`, `archived`, `purge_requested`, `purged` | Forward only | Tombstone and provider ref remain; purge is irreversible |
| Repository | requested/provisioned/protected in operation evidence | Forward reconciliation of same identity | Repository deletion is not a normal catalog transition |

Lifecycle reversal is recovery, not routine reconciliation. It requires an explicit
operator override and never permits identity substitution.

## Journal and checkpoints

A reconciliation journal record contains:

- immutable `binding_id` and unique operation ID;
- desired and applied catalog commit SHAs;
- lifecycle and stage/checkpoint;
- lease owner plus bounded acquire/expiry timestamps;
- attempt, start, update, and completion timestamps;
- sanitized error type/message category;
- provider result identifiers needed for import/resume.

It never contains access tokens, passwords, private keys, database content, or response
bodies. A completed binding at the same desired SHA is idempotent unless an operator uses
the reviewed drift-reconciliation override.

## Gate model

| Gate | Default | Evidence required |
| --- | --- | --- |
| AWS/account apply | Disabled outside protected environment | Reviewed plan, approval, quotas, backend and role readiness |
| Repository mutation | Disabled in CI | Seeded template, local GitHub App runtime, reviewed import/migration plan |
| Kubernetes tenant apply | Disabled until local inventory gates pass | Backup/restore verification, capacity, cluster health, serialized operator run |
| Argo CD/Kyverno | Disabled | Compatibility plus live readiness, policy, rollback and reboot evidence |
| Supabase live adapter | Disabled | Credential rotation, sensitive state, hosted canary and explicit live-service gates |
| Supabase purge | Disabled | `purge_requested`, exact UID:catalog-SHA confirmation, reviewed destroy plan |
| Booking production | Disabled | Sentinel, dry-runs, alarms, idempotency, scheduler cutover evidence |

## State sensitivity

OpenTofu state containing a Supabase database password is credential-equivalent. It uses
a dedicated encrypted bucket/key boundary with deletion denial and object-level audit
events, and ordinary read-only agents cannot access it. RepoWise and Graphify outputs are
credential-free, ignored, reproducible, and non-authoritative.
