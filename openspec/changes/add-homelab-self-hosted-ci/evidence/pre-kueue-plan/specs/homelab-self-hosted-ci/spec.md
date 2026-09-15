## Purpose
Run repository CI on existing homelab hardware with disposable execution isolation and preserved GitHub deployment evidence.

## ADDED Requirements

### Requirement: Bounded independent execution
CI SHALL run outside Talos on a 4-vCPU, 16-GiB VM with a 100-GiB disk. Worker RAM SHALL become 156 GiB while existing Talos CPU and disks remain unchanged. Total assigned RAM MUST remain 176 GiB.

#### Scenario: Worker maintenance
- **WHEN** the Talos worker is restarted
- **THEN** the CI manager remains available and can verify recovery

### Requirement: Disposable job isolation
Each job MUST execute in a fresh nested Linux guest. Manager registration credentials MUST remain inaccessible to guests. At most one guest SHALL execute at a time. Fork work MUST NOT execute. Guest networking MUST deny direct manager and LAN management access, permitting authorized private deployment through existing job credentials.

#### Scenario: Completion or recovery
- **WHEN** a job completes, fails, is cancelled or the manager restarts
- **THEN** its guest and writable disks are removed before any new guest can execute

### Requirement: Controlled runner operations
The manager SHALL provide pause, resume and status. Pause MUST allow active work to finish. KVM failure, disk pressure or failed cleanup MUST block new work. Diagnostics MUST NOT expose credentials.

#### Scenario: Pause or failure
- **WHEN** admission is paused or a prerequisite fails
- **THEN** no additional guest starts and status explains the blocking reason

### Requirement: Preserved GitHub safeguards
All workflows SHALL use self-hosted execution without automatic paid fallback while retaining job names, protected environments, OIDC credentials, apply confirmation and required acceptance gates. ARM artifacts MUST retain ARM compatibility. Checks MUST identify their actual source commit.

#### Scenario: Local deployment first
- **WHEN** the assembled source has already been deployed locally
- **THEN** CI performs a fresh drift check, reports actual changes and never applies intermediate stack branches as a rollback

#### Scenario: Failed required job
- **WHEN** required acceptance fails, cancels or unexpectedly skips
- **THEN** merging remains blocked

### Requirement: Reproducible recovery and evidence
Hardware and guest setup SHALL be repository managed, with pinned image inputs, unchanged state backends and guarded saved plans. Local checks and live behavior MUST be recorded separately. Administration-machine bootstrap MUST remain available independently of CI.

#### Scenario: Rebuild
- **WHEN** the runner VM is lost
- **THEN** an administrator can rebuild from pinned configuration and independently issued credentials without recovering a previous job disk
