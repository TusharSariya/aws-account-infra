# Service and external-provider vending

Service vending is catalog-driven and deliberately split by authority. GitHub-hosted CI
performs deterministic validation only. AWS account creation uses the existing protected
GitHub environment, Kubernetes remains Ansible-owned, GitHub repository vending runs
locally through a GitHub App, and external providers reconcile locally through a
serialized journal.

## Current safety boundary

Supabase v1 creates one dedicated project per service. Shared projects, shared Auth, a
custom Auth gateway, Storage, public signup, custom SMTP, database row access for agents,
and backup or RPO promises are out of scope. A Free project may be paused for low activity;
archive means best-effort retention until an explicit purge, not recoverability.

The existing harvester project is not a vending target. Its legacy service-role key must
be rotated before the first vended project, and Ansible now sends its Secret manifest only
over `kubectl apply --filename -` stdin. Values no longer appear in process arguments,
temporary files, registered output, or diffs.

`catalog/external-provider-gates.json` is fail-closed. Live canary reconciliation requires
the harvester credential rotation and sensitive-state gates. Normal service vending also
requires the template, hosted adapter canary, and explicit live-enable gates. Gate changes
must cite reviewed evidence in the commit or pull request; code does not infer success.

## Catalog versions

V1 normalization preserves the historical `test` and `tofu-plan` branch checks. V2 has
no inherited check list: every repository declares only contexts its own workflow emits.
The JSON Schema accepts both versions, and Python normalizes them to one v2 internal
shape before uniqueness, previous-version, lifecycle, and capacity checks. V2 permits an
external-only service by allowing empty `accounts` and `kubernetes` maps:

```yaml
version: 2
provisioner: service-v2
service:
  uid: 4fa03054-6f90-4f96-bd58-b9b6c08aa07c
  id: auth-canary
  display_name: Auth Canary
  owner: platform
repository:
  identity: TusharSariya/auth-canary
  name: auth-canary
  visibility: private
  template: service-stack-template
  migration: template
  protection_profile: service
  spec_layout: root
  required_status_checks: [test]
  agent_data_access: none
accounts: {}
kubernetes: {}
external_services:
  supabase:
    lifecycle: active
    organization_id: example-org
    project_name: auth-canary
    project_ref: null
    region: us-east-1
    plan: free
    storage: disabled
    backup_profile: none
    auth:
      mode: operator-only
      site_url: https://auth-canary.example.com
      redirect_urls: [https://auth-canary.example.com/auth/callback]
      public_signup: false
```

After the first apply, record the provider-assigned ref and commit it:

```bash
python3 scripts/service-catalog.py record-supabase-ref auth-canary abcdefghijklmnopqrst
```

Catalog UID, service ID, repository identity, Supabase organization, name, region, and a
recorded project ref are immutable. Supabase lifecycle is one-way:
`active -> suspended -> archived -> purge_requested -> purged`. Suspended and archived
projects are retained by OpenTofu. Application credential revocation is a service-repo
operation and must complete before committing either state.

## Management-account control plane

Apply `live/aws/organization/external-control` from the management account. It creates:

- a dedicated KMS key and versioned state bucket with object deletion denied;
- a KMS-encrypted, point-in-time recoverable DynamoDB reconciliation journal and a
  separate ephemeral OpenTofu lock table;
- a local reconciler role trusted only by exact configured principals;
- least-privilege access to one exact runtime secret ARN.

The Supabase database password is necessarily stored in OpenTofu state. Anyone able to
read this state must be treated as able to read a credential. Do not grant the ordinary
AWS read-only permission set access to this bucket or its KMS key.

After `external-control` exists, reapply the organization security root with its exact
state bucket ARN as `external_state_bucket_arn`. This turns on CloudTrail S3 object data
events for state reads and writes; management-event logging alone does not audit them.

The journal records `binding_id`, operation ID, desired and applied catalog commit SHAs,
lifecycle, stage, bounded lease ownership, timestamps, sanitized error type, and provider
result identifiers. It never stores provider credentials.

A completed binding at the same catalog SHA is a no-op. Use `--force` only for a reviewed
drift-reconciliation run; it re-plans the provider without weakening lifecycle gates.

## Reconciliation

Install the local runtime dependency, validate with the fake adapter, and inspect the
journal before enabling a provider:

```bash
python3 -m pip install -r requirements-external.txt
python3 scripts/external-provider-reconciler.py auth-canary \
  --adapter fake --catalog-sha "$(git rev-parse HEAD)"
```

Prepare one sensitive backend config per service using outputs from `external-control`.
Live runs require a clean, committed catalog and existing backend resources. The
reconciler isolates provider caches per service and reinitializes against that service's
exact backend config. Resolve both the PAT and database password only inside the child
process:

```bash
cp live/external/supabase/backend.hcl.example /secure/path/auth-canary-backend.hcl
```

Use a distinct state key per service. Keep the populated backend file outside the
repository even though it contains identifiers rather than credential values.

```bash
asm-exec -- env \
  'SUPABASE_ACCESS_TOKEN={{resolve:secretsmanager:platform/supabase-reconciler:SecretString:access_token}}' \
  'TF_VAR_database_password={{resolve:secretsmanager:platform/supabase-reconciler:SecretString:database_password}}' \
  python3 scripts/external-provider-reconciler.py auth-canary \
    --adapter tofu --journal dynamodb \
    --journal-table external-provider-reconciliation \
    --backend-config /secure/path/auth-canary-backend.hcl
```

Do not enable shell tracing. The Supabase provider is the only normal mutation path.
`scripts/supabase-restore.py` is the sole exception and requires the exact immutable
project ref plus checked-out catalog commit. It is operator-only because restore is a
Management API mutation that OpenTofu does not perform.

Create the canary operator through a reviewed Dashboard invite or equivalent protected
operator procedure before disabling signup. Do not distribute a service-role or secret
API key to the service repository, browser, agents, or Kubernetes workloads.

Purge requires both `lifecycle: purge_requested` and a confirmation formed from the
service UID and exact catalog SHA:

```bash
python3 scripts/external-provider-reconciler.py auth-canary --adapter tofu \
  --journal dynamodb --journal-table external-provider-reconciliation \
  --backend-config /secure/path/auth-canary-backend.hcl \
  --confirm-purge 4fa03054-6f90-4f96-bd58-b9b6c08aa07c:COMMIT_SHA
```

Review the destroy plan before approval. After the journal records a completed purge,
commit `lifecycle: purged`. Tombstones remain forever and IDs are never reused.

## Auth canary and release gate

The v1 canary is operator-only. Run `scripts/supabase-auth-canary.py` beneath `asm-exec`.
It verifies public signup is rejected, then checks operator password login, refresh,
password-recovery acceptance for the exact HTTPS redirect, logout, and refresh-token
revocation without printing response bodies. Access JWTs may remain valid until expiry;
logout is not represented as immediate access-token revocation.

Provider adapter releases require a unique ephemeral hosted project, the full lifecycle
through purge, and a permanent tombstone. Weekly testing uses local fake/Supabase tests
and read-only health checks against an existing remediated project, preserving the final
Free-plan slot.

Pass `--canary` only for that ephemeral release gate. It bypasses the not-yet-earned
`adapter_canary_passed` and live-service gates, but never bypasses harvester rotation or
sensitive-state readiness.

## Repository bootstrap and agent access

`live/aws/organization/template-bootstrap` creates the template repository without a
template dependency. Seed it once from `templates/service-stack`, review the initial
commit, then enable the profile-specific required checks. Service repos and this
infrastructure monorepo keep numbered Spec Kit features at `specs/`. HTTP API
descriptions are separate contracts under `contracts/openapi/`.

RepoWise and Graphify are opt-in local analysis tools. The golden repo wrapper compares
the complete worktree before and after analysis and fails if a tool writes generated
artifacts into the repository.

Agents receive the existing AWS `PlatformReadOnly` permission set by default, including
explicit denies for Secrets Manager, SSM parameter values, and KMS decryption. Step-up is
requested through the golden repo's structured access issue and applied by an operator
through the separately assigned operator or emergency-admin group. Approval alone grants
nothing, and the request must include an expiry and revocation check. `agent_data_access`
defaults to `none`; v1 creates no service-agent Supabase MCP configuration or database
row access.
