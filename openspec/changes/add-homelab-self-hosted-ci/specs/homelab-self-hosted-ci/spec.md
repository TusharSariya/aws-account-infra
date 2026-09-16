## Purpose
Share bounded Talos application compute while preserving independent recovery and operational controls.

## ADDED Requirements

### Requirement: Shared admission pool
AI, CI and ordinary Argo execution Pods SHALL share one worker-bound Kueue 0.19.4 ClusterQueue with 33.5 CPU, 150 GiB RAM and 60 GiB ephemeral storage. It SHALL use StrictFIFO, equal priorities, no preemption, borrowing or fairness policy. LocalQueues SHALL not partition quota. Oversized submissions MUST be rejected with an actionable error.

#### Scenario: Contention
- **WHEN** an older queued workload cannot fit remaining CPU, RAM or ephemeral storage
- **THEN** newer work waits, existing work continues and reservations release after observed termination

### Requirement: Lifecycle ownership
AI SHALL retain 33.25 CPU / 77 GiB, retained storage, lifecycle-owned desired state/replicas, storage protections and explicit Force Stop semantics. Queue waiting MUST NOT count as idle running time. Runtime template changes MUST wait for AI to be off. Status SHALL expose queue order, resources and blocking reasons alongside existing API states.

#### Scenario: Stop while queued
- **WHEN** the operator stops a queued AI start
- **THEN** the pending Pod is cancelled and its reservation is released after observed termination

### Requirement: Disposable CI execution
ARC 0.14.2 SHALL use the existing repository-scoped GitHub App via a private Secret, separate controller/runner namespaces and minRunners=0 and no ARC maximum. One scale set per reviewed catalog configuration SHALL permit arbitrary whole-millicore CPU and MiB memory/scratch budgets within the shared pool. Jobs SHALL select deployed names through runs-on; unknown and oversized configurations MUST fail pre-merge validation. Whole-Pod effective requests and limits SHALL match the catalog including initialization and Docker overhead. The compatible homelab-talos SHALL retain 4 CPU / 16 GiB / 30 GiB with Docker; lightweight and checks configurations SHALL start at 1 CPU / 2 GiB / 2 GiB and 2 CPU / 4 GiB / 4 GiB without Docker. Each SHALL use bounded disposable volumes and no host filesystem or Docker socket mounts. Fork execution MUST be disabled.

#### Scenario: Cancellation or expiry
- **WHEN** GitHub cancels or expires a waiting runner request
- **THEN** the disposable runner workload is removed without leaking reservations

### Requirement: Argo and operational availability
Ordinary Argo Pods SHALL use per-Pod Kueue admission with execution deadlines that exclude queue waiting. Reviewed templates, UTC schedules, Forbid overlap and mutexes SHALL remain. Platform and Start/Stop/Force Stop/Status Pods MUST run outside Kueue even when its controller is unavailable. Compute submissions MUST NOT bypass admission.

#### Scenario: Queue outage
- **WHEN** Kueue is unavailable or the pool is full
- **THEN** Stop/Status and Pi-hole remain usable and ordinary compute cannot start unadmitted

### Requirement: Independent bootstrap and guarded migration
The CI root SHALL use kubernetes/homelab-ci/terraform.tfstate while preserving existing roots and keys. Hosted bootstrap/upgrades/recovery SHALL retain credentials, Tailscale, exact saved-plan guards and approvals. Mac bootstrap SHALL remain available. VM 103 retirement MUST match only its identified CI resources, remove its DHCP reservation/dedicated permissions and retain the GitHub App/key. Worker RAM SHALL be restored gracefully to 172 GiB, with allocatable and Pi-hole verified before pool activation.

#### Scenario: ARC absent
- **WHEN** runners or Kueue are unavailable
- **THEN** hosted or Mac recovery can restore the platform independently

### Requirement: Explicit cutover and evidence
Routine workflows SHALL select github-hosted or talos via CI_EXECUTOR, without automatic paid fallback. Talos cutover MUST follow actual acceptance including ARM packaging and private deployments. Three reviewed PRs, fresh empty post-deployment plans and existing merge gates SHALL be required. Previous evidence/failures MUST be preserved and local checks MUST NOT be reported as GitHub success.

#### Scenario: Unobserved acceptance
- **WHEN** runtime verification has not succeeded
- **THEN** its task remains unchecked and Talos cutover stays disabled

### Requirement: Measured storage and listener capacity
Deployment SHALL fail unless fresh measured root/image storage, platform requests,
the 60-GiB compute quota and 8-GiB additional storage headroom fit the worker.
It SHALL account for desired ARC listeners and available Pod slots, preserve the
118-GiB RAM platform reserve, wait for runners to become idle, and never consume
retained AI storage. Jobs SHALL install only their required prerequisites.

#### Scenario: Insufficient disk headroom
- **WHEN** measured storage or listener/Pod capacity cannot support the catalog
- **THEN** deployment fails before changing admission and routing remains disabled

#### Scenario: Mixed runner concurrency
- **WHEN** simultaneous differently sized runners fit shared CPU, RAM and scratch
- **THEN** Kueue admits them concurrently and releases reservations after termination

#### Scenario: Independent expiry observation
- **WHEN** a GitHub job remains queued for the documented 24-hour timeout
- **THEN** external monitoring records actual expiry separately from cancellation and verifies fixture cleanup

### Requirement: Bounded local dependency and build caches
Nexus Community Edition and PostgreSQL SHALL run in isolated platform Pods using
2 CPU / 8 GiB and 0.5 CPU / 2 GiB respectively, within the 4 CPU / 18 GiB platform
reserve. XFS project quotas SHALL enforce exactly 64 GiB on the separate data disk:
48 GiB content, 8 GiB database/configuration and 8 GiB temporary/logs. Deployment
MUST account for retained volumes, physical thin-pool headroom and fresh measurements
including service images before admitting 60 GiB scratch plus 8 GiB eviction headroom.

#### Scenario: Cache footprint does not fit
- **WHEN** service images, retained volumes or measured physical headroom prevent the approved budget fitting
- **THEN** deployment fails without reducing reserves or enabling global routing

### Requirement: Shared cache operation and access
Nexus SHALL proxy npm, PyPI, APT, Go and workflow registries, use raw repositories
for pinned tools and a separate hosted Docker build cache. Consumers SHALL be
read-only; build writers SHALL have no administration or trusted release write
permissions. Credentials MUST NOT enter caches. Integrity checks, lockfiles,
signatures and image digests SHALL remain enabled. Reviewed pinned runner images
SHALL carry recurring prerequisites. GitHub cache reads/writes and automatic
setup-action caching SHALL be disabled, with free allowance and $0 paid cache spend.

#### Scenario: Cache unavailable
- **WHEN** reads miss or the cache is unavailable
- **THEN** bounded retries permit verified upstream downloads and bootstrap/recovery remain independent

#### Scenario: Upload fails
- **WHEN** an otherwise successful build cannot upload its disposable cache
- **THEN** the successful build result remains valid

### Requirement: Supported cleanup and warning thresholds
Supported Nexus cleanup and compaction SHALL reclaim eligible content before
exhaustion. Storage warnings SHALL fire at 80% and CE component/request warnings
at 75%. Soft quotas SHALL alert and XFS quotas SHALL enforce. Paid expansion MUST
NOT be enabled automatically. User-authorized UI creation of cleanup policies and
compaction schedules SHALL be verified during deployment.

#### Scenario: Soft deletion
- **WHEN** cleanup soft-deletes eligible components
- **THEN** supported blob compaction reclaims their physical bytes without direct blob-file deletion

### Requirement: Evidence-based scratch sizing
Each eligible job SHALL be measured once cold and twice warm on fresh runners,
including checkout, installation, images, layers, temporary files and logs.
Scratch SHALL equal the maximum plus 25% and 1 GiB rounded upward to whole GiB,
with a 2-GiB minimum. Adoption MUST follow a successful run at that limit.
The existing homelab-talos configuration SHALL remain compatible.

#### Scenario: Missing measurements
- **WHEN** cold/warm measurements or the declared-limit verification are missing
- **THEN** no smaller runner configuration is adopted on estimated evidence

### Requirement: Guarded OS disk expansion
VM 102 scsi0 SHALL expand from 100 to 128 GiB through an exact saved-plan guard
after physical headroom verification. No other disk or VM setting SHALL change.
Talos EPHEMERAL expansion SHALL retain partition/filesystem identities.

#### Scenario: Scratch capacity recovery
- **WHEN** the expanded filesystem is Ready
- **THEN** fresh measurements including Nexus/PostgreSQL images MUST fit 60 GiB scratch and 8 GiB headroom before cache rollout resumes
