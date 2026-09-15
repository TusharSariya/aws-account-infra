## Purpose
Share bounded Talos application compute while preserving independent recovery and operational controls.

## ADDED Requirements

### Requirement: Shared admission pool
AI, CI and ordinary Argo execution Pods SHALL share one worker-bound Kueue 0.19.4 ClusterQueue with 36 CPU and 160 GiB RAM. It SHALL use StrictFIFO, equal priorities, no preemption, borrowing or fairness policy. LocalQueues SHALL not partition quota. Oversized submissions MUST be rejected with an actionable error.

#### Scenario: Contention
- **WHEN** an older queued workload cannot fit remaining CPU or RAM
- **THEN** newer work waits, existing work continues and reservations release after observed termination

### Requirement: Lifecycle ownership
AI SHALL retain 35.75 CPU / 77 GiB, retained storage, lifecycle-owned desired state/replicas, storage protections and explicit Force Stop semantics. Queue waiting MUST NOT count as idle running time. Runtime template changes MUST wait for AI to be off. Status SHALL expose queue order, resources and blocking reasons alongside existing API states.

#### Scenario: Stop while queued
- **WHEN** the operator stops a queued AI start
- **THEN** the pending Pod is cancelled and its reservation is released after observed termination

### Requirement: Disposable CI execution
ARC 0.14.2 SHALL use the existing repository-scoped GitHub App via a private Secret, separate controller/runner namespaces and minRunners=0/maxRunners=1. Trusted Docker-in-Docker Pods SHALL request and limit 4 CPU / 16 GiB including Docker, with bounded 30 GiB disposable scratch and no host filesystem or Docker socket mounts. Fork execution MUST be disabled.

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
