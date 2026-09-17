## Why

Provide a bounded database prerequisite for [roadmap #32](https://github.com/TusharSariyaOrg/aws-account-infra/issues/32). The owner explicitly approved one primary and daily logical backups; first-app planning and the broader durability programme remain deferred.

## What Changes

- Deploy CloudNativePG 1.30 and PostgreSQL 18, one primary on the existing worker, 32 GiB retained storage, private TLS access, and isolated application schemas.
- Allocate 2 CPU / 6 GiB by changing platform reserve to 6 CPU / 24 GiB and AI/CI quota to 31.5 CPU / 144 GiB. Ollama requests 29.5 CPU; complete AI requests 31.25 CPU.
- Back up daily at 06:30 UTC to a separate versioned SSE-KMS S3 bucket. Keep the latest successful backup indefinitely and expire previous versions seven days after replacement.
- Add workload-scoped Roles Anywhere credentials, verified staging/promotion, failure/staleness/certificate alerts, onboarding and exact-version disposable restore tooling.

## Capabilities

### New Capabilities
- `apps-postgres`: Private shared database with schema isolation and versioned logical backups.

### Modified Capabilities
- `homelab-workload-scheduling`: Reduce the shared compute reservation to accommodate database platform capacity.

## Impact

Existing Kubernetes Helm/OpenTofu root, AWS recovery root, guarded deployment scripts, secret delivery, image builds, capacity values and specifications. Existing recovery Object Lock, Nexus database, waivers and unrelated infrastructure stay intact. Worker downtime is accepted; no replicas, WAL/PITR, new server, dashboard or first application.
