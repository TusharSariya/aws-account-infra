## Purpose

Provide reproducible private workload scheduling and safe on-demand service control across homelab applications while preserving resource and storage boundaries.

## ADDED Requirements

### Requirement: Authenticated reproducible jobs
The platform SHALL support manual, API-triggered and scheduled jobs from reviewed reusable definitions through an authenticated private UI/API. Jobs MUST declare resource budgets and support cancellation and overlap prevention. Unauthenticated clients MUST not submit or control jobs.

#### Scenario: Invocation paths
- **WHEN** an authorized operator invokes the same definition manually, through the API or on its schedule
- **THEN** each execution uses the pinned definition and exposes its execution status and cancellation result

#### Scenario: Overlap and capacity
- **WHEN** another instance of a non-overlapping job is active or requested resources do not fit
- **THEN** overlapping scheduled work is prevented and resource-constrained work waits without disrupting running workloads

#### Scenario: Concurrent independent jobs
- **WHEN** independent jobs declare budgets that fit the remaining capacity
- **THEN** they can run simultaneously without a global one-workload restriction

### Requirement: Approved service operations
The system SHALL provide Start AI, Stop AI, Force Stop AI and Status. Runtime state MUST survive controller recovery and remain authoritative across CI reconciliation. Concurrent commands MUST have a defined serialized result. The migrated AI service MUST default to off.

#### Scenario: Normal stop
- **WHEN** Stop AI is accepted
- **THEN** new work is rejected, existing work drains and replicas reach zero only after all activity is verified complete

#### Scenario: Force stop
- **WHEN** Force Stop AI is accepted
- **THEN** active work is interrupted, the interruption is observable and the service reaches zero replicas

#### Scenario: CI and recovery
- **WHEN** CI runs or the lifecycle controller restarts while AI is intentionally off
- **THEN** it remains off and Status reports the persisted desired state and observed state separately

#### Scenario: Conflicting commands
- **WHEN** concurrent clients request incompatible lifecycle transitions
- **THEN** the recorded command order determines one consistent desired state without stale reconciliation undoing the newer command

### Requirement: Verified inactivity
The system SHALL shut AI down after a configurable continuous interval of verified inactivity, defaulting to 30 minutes. Chat streams, inference, model downloads, document processing and background agents MUST count as work. Missing, stale or unknown activity MUST prevent automatic shutdown and completion of graceful draining.

#### Scenario: Idle timeout
- **WHEN** all activity sources continuously confirm no work for the configured interval
- **THEN** the service closes admission, rechecks activity and shuts down

#### Scenario: Activity becomes unknown
- **WHEN** a telemetry source fails or controller recovery loses continuity
- **THEN** the verified idle interval resets and automatic shutdown remains blocked until a new complete interval is observed

### Requirement: Atomic AI resource admission
Ollama, Odysseus, Chroma and Searx SHALL share one schedulable Pod, with zero replicas off and one on. Their combined reservation MUST be 35.75 CPU and 77 GiB RAM, including Ollama at 34 CPU and 64 GiB. Platform components MUST have separate budgets and VM CPU/RAM MUST remain unchanged.

#### Scenario: Insufficient capacity
- **WHEN** the aggregate reservation does not fit
- **THEN** the entire AI Pod remains Pending, no subset starts and Pi-hole continues serving DNS

### Requirement: Fail-closed storage admission
AI startup MUST require fresh successful checks of the shared XFS mount, all three project-quota directories and retained volumes and physical Proxmox thin-pool data and metadata capacity. Unavailable or failing results MUST block startup. The three application volumes MUST retain data across stop/start and remain separate from bounded temporary storage.

#### Scenario: Missing mount or exhausted capacity
- **WHEN** a required mount is missing, a filesystem is exhausted, the thin pool lacks safe headroom or capacity evidence is unavailable
- **THEN** Start AI fails closed with an actionable status and no fallback writes to a parent filesystem

#### Scenario: Reset and persistence
- **WHEN** the approved migration reset is performed and AI subsequently stops and starts
- **THEN** reset touches only models, workspace and vector application volumes and subsequent data survives stop/start

### Requirement: Honest acceptance and reconstruction
The platform SHALL document pinned reconstruction, independent credential recovery and separate application data recovery. Deployment, behavior, benchmark and recovery evidence MUST remain separately identified.

#### Scenario: Successful deployment
- **WHEN** CI applies successfully and endpoint health passes
- **THEN** the evidence records those results without claiming interactive behavior, model benchmarks or data recovery that was not exercised

### Requirement: Capacity hysteresis and collection
The platform SHALL collect filesystem space/inodes, project usage and independently authenticated physical thin-pool data/metadata every 30 seconds. Measurements MUST match expected identities and be healthy and at most 90 seconds old. At 80 percent it SHALL warn. At 90 percent it SHALL close admission, alert and gracefully drain. Missing, unhealthy or stale measurements MUST close startup and work admission. Pressure MUST clear only after five continuous healthy minutes below 80 percent. Pressure MUST NOT delete data or force termination.

#### Scenario: Capacity recovers
- **WHEN** every required measurement has stayed below 80 percent and healthy for five minutes
- **THEN** pressure clears but drained AI remains off until explicitly started

#### Scenario: Invalid telemetry
- **WHEN** a measurement is stale, absent, unhealthy, nonfinite, from the future or for the wrong filesystem or pool
- **THEN** admission closes and the healthy recovery interval resets

### Requirement: Shared quota isolation
The existing worker XFS filesystem SHALL enforce project hard limits using stable IDs and inherited project ownership. A restricted platform helper SHALL reconcile quotas without granting quota administration to application containers. Temporary storage SHALL be bounded separately.

#### Scenario: Small disposable enforcement test
- **WHEN** a disposable project exceeds its hard limit while a neighboring project remains below its limit
- **THEN** excess writes fail and the neighbor remains writable without filling production storage

#### Scenario: Quota declaration overcommit
- **WHEN** declared project limits exceed filesystem capacity
- **THEN** configuration remains valid and startup depends on actual fresh capacity evidence

### Requirement: Ordered protected rollout
The platform SHALL deliver storage, aggregate default-off packaging and lifecycle/scheduling as three ordered delivery stages through existing OpenTofu/Helm infrastructure, with lifecycle/scheduling reviewed as a dependency-ordered stack of PRs. Explicitly authorized local execution MAY use the same backend and saved-plan guards when CI is unavailable; its evidence MUST be labeled local and MUST NOT satisfy or bypass GitHub merge checks. Backend keys, dependency ordering, apply label, protected environment and destructive-change guards MUST remain intact. The authorized AI reset MUST stop writers, verify exact identities and record a durable one-time migration that routine CI cannot replay.

#### Scenario: Selected check does not succeed
- **WHEN** a required acceptance job fails, is cancelled or unexpectedly skips
- **THEN** the merge gate fails even if apply succeeded

#### Scenario: Explicit local execution during CI outage
- **WHEN** the user explicitly authorizes local deployment and lifecycle maintenance
- **THEN** the repository runner verifies existing Ready prerequisites, retained Off state, pinned images and the complete non-destructive saved plan
- **AND** it records source and plan hashes, local results and encrypted recovery artifacts independently from GitHub Actions
- **AND** changed source or plan bytes prevent applying or reusing an earlier execution record, and the reset is never replayed

#### Scenario: Dependency-ordered review stack
- **WHEN** an already deployed lifecycle delivery is split into smaller review PRs
- **THEN** each PR targets its immediate predecessor, the combined implementation is preserved, and merges proceed bottom-up into the main branch
- **AND** intermediate source branches are not applied as rollbacks to the already upgraded cluster; deployment uses the assembled reviewed tip and required merge checks remain enforced

### Requirement: Reviewed idle configuration
The controller SHALL accept an integer idleTimeoutSeconds between 60 and 86400 from repository-managed Helm configuration, defaulting to 1800. Status SHALL report the effective timeout. Invalid values MUST prevent startup. Configuration changes and controller recovery MUST begin a fresh verified interval; they MUST NOT weaken activity verification or graceful Stop.

#### Scenario: Convenient five-minute interval
- **WHEN** the reviewed homelab configuration selects idleTimeoutSeconds 300
- **THEN** 300 continuous seconds of verified inactivity request normal Stop, and acceptance verifies that configured interval
