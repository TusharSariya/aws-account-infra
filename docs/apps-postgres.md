# Application PostgreSQL

This bounded prerequisite for [roadmap #32](https://github.com/TusharSariyaOrg/aws-account-infra/issues/32) provides one primary, not physical HA. First-app planning and the broader durability programme remain deferred. Nexus PostgreSQL is independent.

## Connection and onboarding

Use `apps-db-rw.homelab-data.svc.cluster.local:5432`, database `apps`, `sslmode=verify-full`, and the `ca.crt` from `homelab-data/apps-db-ca`. No external ingress is created; optional read and read-only services are disabled. Never distribute the generated owner secret or PostgreSQL superuser credentials to apps. The owner is NOLOGIN.

Create two independent 256-bit passwords (`secrets.token_urlsafe(32)`) in a mode-0600 JSON file outside Git with keys `runtime` and `migration`. Create the intended application namespace, then run:

```sh
python3 scripts/postgres_onboard.py myapp --namespace myapp --credentials /private/myapp.json
```

The repeatable command sends credential content through stdin to Kubernetes, never Terraform. It creates `app_myapp`, `app_myapp_migration` and `app_myapp_runtime`; distinct Secrets `app-myapp-migration` and `app-myapp-runtime` contain `username`, `password`, `ca.crt` in both the app namespace and `homelab-data`. CNPG manages their passwords through DatabaseRole objects. Wait for role reconciliation before connecting. Runtime pods mount only their runtime Secret; only explicitly invoked migration jobs mount migration credentials. Namespace administrators can read namespace Secrets, so namespace RBAC remains an operator boundary.

Database ingress requires **both** namespace and Pod labels `homelab/apps-db-client: "true"`. Add a matching egress rule in the app namespace permitting TCP 5432 to `homelab-data` Pods labeled `cnpg.io/cluster: apps-db`, plus DNS. Labels are operator-controlled authorization, not a security boundary against namespace administrators. Backups have their own narrow policy; operator management port 8000 is restricted to CNPG.

Migration owns only the private schema. Runtime receives SELECT/INSERT/UPDATE/DELETE on its tables and USAGE/SELECT on sequences, including future objects created by its migration role. No implicit shared privileges or runtime DDL. Run reviewed shared-table grants as an operator, for example:

```sql
GRANT USAGE ON SCHEMA shared TO app_myapp_runtime;
GRANT SELECT ON shared.countries TO app_myapp_runtime;
```

Shared objects should be owned by `apps_owner`. Functions and types require explicit grants; default PUBLIC execution/type access is revoked. Onboarding serializes with backup. Hold advisory lock `748930126` during role/DDL administration and schedule migrations outside the daily backup window.

## Capacity and deployment order

PostgreSQL requests/limits 1 CPU / 4 GiB; CNPG 250m / 512 MiB; backup 500m / 1 GiB. An independent failure monitor uses 100m / 128 MiB from management headroom. This fits the approved 2 CPU / 6 GiB allocation. A namespace compute quota prevents a second manual backup from reserving another 500m / 1 GiB while it waits. Platform reserve is 6 CPU / 24 GiB, AI/CI pool 31.5 CPU / 144 GiB, and AI 31.25 CPU (Ollama 29.5). VM resources are unchanged.

The retained database claim starts at 32 GiB; backup scratch is a retained, disk-backed 64 GiB claim on the same worker data disk. `worker-local-retain` does **not** enforce PVC sizes as disk quotas and has `allowVolumeExpansion: false`. A size edit cannot grow this storage in place. Growth needs a separately reviewed migration. The backup process limits dump bytes to 30 GiB and archive bytes to 32 GiB, leaving metadata headroom under 64 GiB; a too-large backup fails without replacing latest. This protects this process, not arbitrary writers to the PVC. Preflight requires the expected XFS mount and at least 112 GiB free (32 + 64 + 16 headroom).

1. Apply the AWS recovery root's saved plan and enroll the dedicated certificate.
2. Build `apps/containers/postgres-backup/Dockerfile` through `postgres-backup-image`, verify its output, pin the digest in `postgres-values.yaml`, and set the nonsecret AWS output coordinates. Enable backups only with these inputs.
3. Store base64 of private enrollment JSON (`password`, `client.crt`, `client.key`) in prod environment secret `POSTGRES_BACKUP_CREDENTIALS_B64`. Kubernetes credential reconciliation bypasses OpenTofu. Copy the existing read-only registry Secret to `homelab-data` through that reconciliation.
4. Wait for AI and queued CI work to be idle, then use `scripts/homelab-ci.py` plan/apply for the reduced pool. Do not stop work to reclaim capacity. Existing admission safeguards remain authoritative.
5. Apply the complete guarded Kubernetes root plan. `postgres_preflight.verify` checks the reduced live queue, idle workload inventory and mounted disk space immediately before apply. Run the same preflight for an authorized local deployment. Do not weaken drift, saved-plan or backend checks.
6. Verify cluster Ready, secrets, TLS/network policy, restart persistence, backup and two restores. A successful Helm apply alone is not acceptance.

## Backup and retention

CronJob `homelab-data/apps-db-backup` runs at 06:30 UTC, retries twice within a two-hour deadline, and uses Forbid scheduling. All runs additionally hold a kernel lock on the shared scratch PVC plus a PostgreSQL advisory lock, so manual jobs share serialization:

```sh
kubectl -n homelab-data create job --from=cronjob/apps-db-backup apps-db-backup-manual-$(date +%s)
```

The archive contains custom-format `pg_dump --create`, password-free role metadata/memberships, database/system version and checksum manifest. Backup has `pg_read_all_data` and BYPASSRLS, with no superuser or object write grants. Unknown roles fail closed rather than silently omitting ownership.

A unique staging object is read back and SHA-256 verified before an atomic multipart copy publishes `apps-db/latest.tar.gz`. The resulting exact version is read back and verified, checked against current, then recorded in logs and followed by the success heartbeat. Dump, staging upload and checksum failures cannot replace latest. Incomplete promotion never completes a new version. The workload cannot delete objects or versions.

The separate S3 bucket uses versioning, SSE-KMS, blocked public access, HTTPS-only access and an explicit DeleteBucket deny. **Current latest never expires.** Noncurrent latest versions become eligible for expiration seven days after replacement, without a retained-version-count exception. Staging current and noncurrent objects expire after one day; incomplete multipart uploads abort after one day. Lifecycle deletion is asynchronous. The existing recovery bucket's 30-day Object Lock is unchanged. See [S3 lifecycle semantics](https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-expire-general-considerations.html).

A 15-minute monitor with read-only Job-list permissions detects terminal failed Jobs independently of the backup process, including OOM/deadline failures. CloudWatch sends the existing account-security-alerts SNS destination backup failures, approximately 30 hours without verified success, and certificate expiry within 30 days. Failed authentication can prevent sending failure metrics; the independent missing-success alarm remains effective. Daily logical backups target roughly one day of data loss when successful; failures extend that window.

## Credential lifecycle

Use the repository [certificate enrollment procedure](../live/aws/staging/workloads/homelab-recovery/IDENTITY.md) with CN `homelab-postgres-backup-01` and a dedicated CA. Only leaf `client.crt` and `client.key` enter Kubernetes. Signing material stays outside the cluster, Git and OpenTofu state. The public CA is in the reviewed tfvars. The image pins AWS signing helper 1.8.5 and its checksum; the [credential process](https://docs.aws.amazon.com/rolesanywhere/latest/userguide/credential-helper.html) automatically obtains refreshable temporary credentials.

Initial local enrollment is under `~/.config/aws-account-infra/postgres-backup-01/` (0700); the encrypted CA key, its private passphrase file, leaf key and credential JSON are 0600. Move the CA passphrase into independently recoverable password-manager custody and preserve an encrypted CA backup independently of this machine. These local files alone are not independent recovery evidence. Renew at day 60. On compromise disable `postgres_identity_enabled`, revoke existing role sessions if needed, issue a new key and CN, update the public identity inputs and re-enroll. Never place CA key/passphrase in a Kubernetes Secret.

## Exact-version restore

Create a separate disposable PostgreSQL 18 instance with admin access and no `apps` database. It must have a different system identifier; the command refuses the production hostname, matching system identifier, or an existing `apps` database. Use a private file with fresh passwords keyed by every archived login (including `apps_backup`). Preserve CA verification for remote connections. Use independent authorized AWS recovery credentials or the scoped backup identity for exact-version retrieval:

```sh
# PGHOST points to the disposable instance, PGUSER to its administrator.
# PGPASSWORD or PGPASSFILE is supplied privately; never put passwords in URLs/arguments.
export PGDATABASE=postgres PGSSLMODE=verify-full PGSSLROOTCERT=/private/restore-ca.crt
python apps/platform/postgres/restore.py --bucket homelab-postgres-992382747916-us-east-1 \
  --version-id EXACT_VERSION_ID --passwords /private/fresh-passwords.json --scratch /private/scratch
```

Use the built backup image or its pinned dependencies and PostgreSQL 18 client tools. Scratch needs 64 GiB free. Archive extraction rejects links, unexpected members, oversized files and checksum mismatches. It recreates reviewed role attributes/memberships with fresh passwords, then restores database ownership, data and grants. If it fails after creating objects, dispose of the test instance before retrying; no automatic cleanup targets production. Database-specific role settings are carried by `pg_dump --create`.

Restore current and older exact versions into separate disposable instances, then verify expected rows, table owners, runtime/migration boundaries, shared grants and RLS. Record version IDs and checksums, never credentials. No automatic replacement of the production database is offered.
