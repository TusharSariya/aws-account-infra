## Context

See proposal.md. Existing Helm releases use checksum-verified chart archives, immutable images, guarded complete saved plans and protected secret reconciliation. The worker data disk hosts retained local-path volumes and selected XFS quotas. The recovery root already owns a distinct Object-Locked bucket.

## Goals / Non-Goals

Deliver the approved single primary and recoverable daily archives within 2 CPU / 6 GiB. No first application, replica, WAL archive, new server, dashboard or broad recovery programme.

## Decisions

- CloudNativePG manages one PostgreSQL 18 primary and certificates. Disable optional read/read-only services. Reject non-TLS TCP connections; clients use verify-full and the server CA. Network policy grants database access only to explicitly selected clients and backup jobs, plus operator management traffic.
- Use one `apps` database, non-login owner and empty `shared` schema. App migration logins own only their private schemas, runtime logins receive explicit DML and sequence grants. PUBLIC gets no database/public-schema privileges. Backup has pg_read_all_data and BYPASSRLS, never superuser. Capture role attributes/memberships without password hashes.
- Serialize every scheduled/manual backup using a kernel lock on the shared scratch PVC and a PostgreSQL advisory lock held on a dedicated live connection. The kernel lock prevents overlap even if the database connection is lost. Abort publication if that connection fails. Dedicated 64 GiB local-path scratch PVC uses disk and serial access; local-path sizes are requests, not enforced quotas. Fail before deployment without fresh worker free-space evidence.
- Stage each complete archive under a UUID, verify full readback SHA-256, then promote and verify the exact new S3 version. Use multipart transfers for archives over 5 GiB. Only verified publication emits success. A separate bounded monitor reports terminal Kubernetes Job failures and certificate expiry; the AWS missing-success alarm remains independent of Kubernetes health. Exact alarm ARNs are authorized in the existing SNS topic policy. Current latest never expires; noncurrent latest expires seven days after replacement, staging current/noncurrent after one day.
- Use dedicated certificate-scoped Roles Anywhere with no delete/admin permissions. CA stays outside Kubernetes. Secret payloads bypass Helm/OpenTofu and subprocess logs. Restore accepts exact version and requires a distinct disposable endpoint; fresh role credentials are installed separately before restoring ownership/grants.

## Risks / Trade-offs

- Worker failure causes downtime; daily success implies roughly one day RPO. Failed runs extend data-loss exposure.
- Local-path requests are not disk quotas; bound scratch writes in the backup process and verify physical capacity. StorageClass cannot expand in place; future growth needs a reviewed migration.
- Role/DDL changes during dump can complicate logical consistency; serialize onboarding with the backup lock and schedule app migrations away from backup.
- Certificate enrollment, image publication and live acceptance depend on available credentials and connectivity. Local/mock checks never substitute for live evidence.

## Migration Plan

Deploy AWS resources and enroll identity first. Build/pin the backup image and reconcile credentials. Wait for AI/CI to become idle, reduce shared quota, then apply operator/database and AI reservation changes through saved-plan guards. Verify isolation, TLS, restart persistence, failure injection, exact versions, denied deletion and two disposable restores. Rollback must preserve database PVC and S3 versions; never automatically destroy data or restore over the running database.
