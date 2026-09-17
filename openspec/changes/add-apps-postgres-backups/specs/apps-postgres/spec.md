## Purpose

Provide a private shared application database with explicit schema isolation and independently verifiable versioned daily logical backups.

## ADDED Requirements

### Requirement: Bounded private primary
The platform SHALL run one PostgreSQL 18 primary named apps-db in homelab-data on talos-worker-01 using a supported CloudNativePG 1.30 release. Database, operator and backup SHALL request 1 CPU/4 GiB, 250m/512 MiB and 500m/1 GiB respectively, within 2 CPU/6 GiB. It SHALL use a retained 32 GiB data claim and disk-backed scratch bounded to 64 GiB, outside AI/CI admission. Deployment MUST verify physical free space. PVC requests MUST NOT be represented as disk quotas or expandable storage. Only the private read/write Service SHALL be exposed, using TLS and explicit network policies.

#### Scenario: Restart and connectivity
- **WHEN** the database pod restarts
- **THEN** data survives on retained storage and only authorized TLS clients can reconnect at apps-db-rw.homelab-data.svc.cluster.local:5432

### Requirement: Isolated application access
The apps database SHALL begin with an empty shared schema and no real application. Onboarding SHALL create separate migration/runtime logins and an app-private schema. Runtime access and shared-table permissions MUST be explicit; apps MUST NOT receive superuser or database-owner credentials. Public creation and broad defaults SHALL be revoked. Secrets MUST bypass Git and OpenTofu state.

#### Scenario: Concurrent temporary apps
- **WHEN** two test apps write and read concurrently
- **THEN** each succeeds in its own schema, cross-schema access fails and shared-table access succeeds only after an explicit grant

### Requirement: Verified versioned daily backup
A serialized job SHALL run at 06:30 UTC daily, retry within a two-hour deadline, and archive custom pg_dump data including RLS-protected rows, password-free role definitions, checksums and restore metadata. Scheduled and manual runs MUST share serialization. A separate encrypted, versioned, HTTPS-only, private deletion-protected S3 bucket in us-east-1 SHALL retain apps-db/latest.tar.gz indefinitely as current, with noncurrent versions expiring seven days after replacement and no retained-version-count exception. Staging and its versions SHALL expire after one day; incomplete multipart uploads SHALL abort after one day. Existing recovery Object Lock MUST remain unchanged.

#### Scenario: Failed dump upload or checksum
- **WHEN** dump, staging upload or checksum verification fails
- **THEN** latest is unchanged and no success heartbeat is emitted

#### Scenario: Publication succeeds
- **WHEN** staging readback verifies
- **THEN** publication records and verifies the resulting exact S3 version before sending success

### Requirement: Restricted backup identity and alerts
Backup SHALL use a dedicated Roles Anywhere leaf certificate with temporary credentials and no object deletion or bucket administration. The CA private key MUST stay outside Kubernetes. Existing SNS SHALL alert for failed runs, approximately 30 hours without success and approaching certificate expiry.

#### Scenario: Restricted identity
- **WHEN** the workload attempts deletion or bucket administration
- **THEN** access is denied while upload, exact-version readback and scoped monitoring succeed

### Requirement: Independent exact-version restore
Restore SHALL accept an exact S3 version, verify checksums and restore data, ownership and grants into a separate disposable instance with freshly supplied role credentials. It MUST NOT automatically overwrite the running database.

#### Scenario: Current and older backups
- **WHEN** current and older versions are restored separately
- **THEN** their expected data and permissions are verified and evidence records both results before acceptance is complete
