## Second scratch expansion, 2026-09-16 (America/St_Johns)
The user requested another doubling at the next available maintenance window.
The deployed pool is now 240 GiB shared scratch after an exact VM 102 scsi0
expansion from 192 to 320 GiB. Preserve 33.5 CPU / 150 GiB RAM, the
4 CPU / 18 GiB platform reserve, 8 GiB scratch headroom, separate 64 GiB cache,
all retained volume identities and existing provisional per-job reservations.
The guarded disk and queue applies passed, EPHEMERAL grew exactly 128 GiB,
both post-deployment plans are empty, and Pi-hole/Nexus recovered with AI Off.
The 240-GiB scratch exhaustion/FIFO/cancellation fixture passed. Fresh ordinary
CI concurrency and remaining full rollout acceptance still require evidence.
Earlier dated deployment sections retain historical sizes and receipts.

## Context
The approved migration replaces VM 103 with trusted ARC Docker-in-Docker Pods on Talos. Historical VM implementation and failed attempts remain evidence, not migration acceptance.

## Goals / Non-Goals
Kueue reserves declared requests. Kubernetes schedules and enforces limits. The lifecycle controller owns AI desired state, replicas, draining, activity, idle shutdown and storage-pressure protections. ARC owns disposable runners; Argo owns workflow execution. DNS, networking, storage helpers, platform controllers and operational commands stay outside admission.

## Decisions
Install Kueue 0.19.4 and ARC 0.14.2 with OpenTofu-managed Helm in an independent Kubernetes CI root. Use one worker-bound ClusterQueue, StrictFIFO, equal priority, no preemption, no cohort/borrowing/fairness and 33.5 CPU / 150 GiB quota. Namespace LocalQueues are submission points, not reserved partitions. Concurrent reservations must fit; an older waiting large workload blocks a newer smaller one. Reject requests larger than the pool with an actionable message. FIFO starts at Kueue submission, not at GitHub's upstream queue.

AI keeps its aggregate 33.25 CPU / 77 GiB reservation and retained volumes. Use Deployment/Pod integration without transferring lifecycle ownership. Start queues; Stop cancels waiting work or drains running work; Force Stop keeps explicit semantics. Queue waiting cannot accrue idle time. Adopt runtime templates only while off, avoiding two AI reservations. Status adds queue order, resources and blocking reasons without replacing existing API states. Release reservations only after observed termination.

ARC uses separate controller/runner namespaces and the existing repository-scoped GitHub App via a privately enrolled Secret. minRunners=0 with no ARC maximum. Kueue controls admitted concurrency across a repository-managed catalog of arbitrary reviewed CPU/RAM/scratch budgets, with one homogeneous scale set per configuration. Catalog CPU uses cores (whole millicores); memory/scratch use MiB. `homelab-talos` remains 4 CPU / 16 GiB / 30 GiB with Docker; `homelab-talos-light` starts at 1 CPU / 2 GiB / 2 GiB without Docker, and `homelab-talos-checks` at 2 CPU / 4 GiB / 4 GiB without Docker. These are initial job budgets, not universal minimums or fixed tiers. Promote jobs only through reviewed catalog changes deployed before workflow references. OpenTofu generates container budgets; actual rendered effective Pod requests and matching limits must equal the catalog, including restartable Docker and initialization peaks. Preserve the existing release with an OpenTofu moved block and wait for existing runners to become idle before updating it. No host filesystem or host Docker socket mounts. Fork execution is disabled. Preserve ARM artifacts via tested ARM packaging. Verify cancelled/expired GitHub work deletes pending runner workloads.

Argo ordinary execution Pods use plain-Pod admission. Preserve reviewed templates, UTC schedules, Forbid overlap and mutexes. Queue waiting is separate from execution deadlines. Start/Stop/Force Stop/Status Pods bypass Kueue. Admission filtering must allow platform/operations when Kueue is unavailable and prevent compute bypass.

## Migration Plan
PR 1: foundation, independent hosted/Mac bootstrap and recovery, budgets and narrowly guarded retirement of VM 103. Remove only its DHCP reservation and dedicated permissions, retain GitHub App/key. Gracefully restore worker RAM to 172 GiB. Verify node allocatable covers platform reservations plus the pool and verify Pi-hole before activation.
PR 2: pinned Kueue/ARC Helm, admission enforcement, AI/Argo integration, private enrollment and status.
PR 3: CI_EXECUTOR routing, ARM path, acceptance and operations. Default to github-hosted until observed acceptance; never introduce automatic fallback. Hosted bootstrap/upgrades/recovery retain existing OIDC, Tailscale, saved-plan checks and approvals. Keep Mac bootstrap because hosted allowance was exhausted.
Keep AI off throughout migration. Preserve existing state keys and append evidence, including failures. Never credit local checks as successful GitHub checks.

## Risks / Trade-offs
The single worker remains a shared failure domain. Trusted privileged Docker runners are not isolation for hostile fork code. StrictFIFO may leave resources unused while the head waits. Per-Pod Argo admission is not atomic workflow admission. Controller failure must not strand operational commands.

## Validation
Verify pinned artifacts, rendered Helm, OpenTofu plans, workflow contracts, admission/security policies and strict OpenSpec. Exercise AI-first/CI-first contention, FIFO head blocking, CPU/RAM exhaustion, cancellation, controller/node restart and reservation cleanup. Prove Stop/Status and Pi-hole during exhaustion and Kueue outage. Run actual ARC checkout/build/ARM/private deployment/quota jobs and hosted recovery with ARC absent. Require fresh empty post-deployment plans and existing merge gates; leave unobserved acceptance unchecked.

## Capacity rebudget, 2026-09-15
Historical measurements and approvals remain in evidence. The approved current
pool is 33.5 CPU / 150 GiB, with 4 CPU / 18 GiB platform reserve including Nexus
(2 CPU / 8 GiB) and PostgreSQL (0.5 CPU / 2 GiB). AI requests 33.25 CPU / 77 GiB
only when admitted; Off retains no compute reservation. Fresh allocatable checks
remain authoritative.

## Shared scratch and job-sized rollout
The shared ClusterQueue also admits ephemeral-storage against 240 GiB, without
separate runner partitions or borrowing. Scratch includes logs, writable layers
and bounded emptyDir volumes. Retained AI PVC storage is never used as compute
scratch. AI keeps 33.25 CPU / 77 GiB; it still prevents a 1-CPU runner from fitting.

At plan and apply, fresh kubelet root/image measurements plus the full scratch
quota and 8 GiB additional storage headroom must fit node allocatable and measured
free bytes. Missing, stale or insufficient measurements fail deployment. Node
allocatable already excludes kubelet eviction reservations. Root use includes
images on Talos; check root and image filesystems independently without adding
image bytes twice. Recheck all desired listener reservations, available Pod slots
and 10 additional platform/Argo slots. Keep the 18-GiB platform RAM reserve.

Audit every routine job, including reusable storage/acceptance and supporting
gates. Select lightweight, checks or Docker-enabled configurations explicitly;
install only requested prerequisites. Bootstrap, admission upgrades, physical
maintenance, independent backups and recovery retain hosted execution and Mac
fallback. Workflow-only changes must not fan out to unrelated state roots.

Deploy admission/catalog first, run explicit Talos proofs including simultaneous
mixed sizes, combined CPU/RAM/storage exhaustion and cleanup, then merge validated
routing and set CI_EXECUTOR=talos. The user waived the independent 24-hour GitHub expiry observation on 2026-09-15
(America/St_Johns). Expiry remains unverified; retain optional tooling without running it. Keep
unobserved acceptance unchecked. Verify actual routine runs, empty plans,
autostart, Pi-hole and AI Off before returning the temporary Actions budget to $0.

## Shared local Nexus cache
Nexus Community Edition and PostgreSQL run as isolated platform Pods on the
existing worker, managed through the guarded OpenTofu CI root. Four retained,
static local PVs on the separate XFS data disk enforce 48 GiB content, 6 GiB
PostgreSQL, 2 GiB Nexus configuration and 8 GiB temporary files/logs. The existing
privileged quota collector owns project assignment; service Pods have no host
mounts or quota privileges. Deployment checks actual hard limits, fresh guest
and physical thin-pool bytes, retained PV commitments and image-inclusive scratch.
The 240-GiB scratch target and 8-GiB eviction headroom are mandatory; failure is a
rollout blocker, not permission to lower headroom.

Proxy npm, PyPI, APT, Go and workflow container registries; raw repositories cache
pinned tool downloads. A separate hosted Docker repository stores disposable build
caches. Consumers receive read/browse permissions only; build writers can add/edit
only build-cache content. Administration and trusted release publication remain
separate. Credentials must never enter cached content. Preserve lockfiles, package
integrity, signed APT metadata, Go checksum verification and image digests. Cache
misses/outages fall back to verified upstream with bounded retries; upload failure
cannot invalidate an otherwise successful build. Bootstrap/recovery can rebuild
from upstream without the cache. Recurring prerequisites belong in reviewed pinned
runner images.

On 2026-09-16 the user accepted stock BuildKit's excessive internal retries for
now after the failed-layer fixture observed four cache and eight upstream
attempts. Do not maintain a patched BuildKit solely to enforce the two/three
attempt limit. This exception covers BuildKit's internal registry/layer retries
only; dependency and pinned-download clients retain at most two cache attempts
then at most three upstream attempts. Preserve the failed retry receipt and
continue outage, interrupted-download, integrity and denied-upload acceptance.
Release publication failures remain fatal. This is separate from the 24-hour
expiry observation waiver.

GitHub dependency/build cache reads and writes, including setup-action automatic
caching, are disabled. Keep the repository cache limit at its free allowance and
paid cache spending at $0. Published releases, deployment artifacts and operational
evidence keep their existing workflows. No automatic paid expansion is permitted.

Use supported Nexus cleanup and blob compaction, never filesystem deletion of
blob content. Warn at 80% storage and 75% of CE limits (30,000 components and
75,000 requests/day); reclaim eligible content before exhaustion. Soft quotas are
alerts; XFS hard quotas enforce storage. On 2026-09-15 the user authorized CE EULA
acceptance and an explicit exception permitting supported UI creation of cleanup
policies/compaction schedules with deployment verification, because Sonatype
marks the cleanup-policy REST API Pro-only. All other desired configuration stays
under the guarded infrastructure workflow.

On 2026-09-16 the user authorized provisional job-specific scratch limits,
followed by fresh-run validation and refinement, instead of requiring the full
cold/two-warm/fourth-run proof before reductions. Label these allocations as
provisional and preserve homelab-talos compatibility. Every eligible job must
succeed on a fresh runner at its declared limit before cutover; inspect failures
and refine the relevant allocation rather than weaken quota enforcement. The
full measurement protocol and `scripts/ci_scratch.py` remain available to qualify
measured budgets using ceil(peak * 1.25 + 1 GiB), minimum 2 GiB. Do not report
provisional allocations as measured or four-run verified.
Deploy services and admission first. Prove cross-runner npm/Python/APT/Docker
reuse with upstream bytes and elapsed time; concurrency, quota rejection,
cleanup/compaction, interrupted downloads, service/node restart, fallback,
AI-first/CI-first contention, Stop/Status/Pi-hole under queue load and outage.
Complete hosted recovery and all other required acceptance before global routing.
The independent 24-hour expiry observation is waived, not verified. Finish with empty plans, AI Off, healthy Pi-hole and no leaked
reservations. Historical evidence is retained and does not prove new budgets.

## Historical worker OS disk expansion (completed)
The user authorized extending the plan after the image-inclusive scratch gate
failed on the 100-GiB worker OS disk. Increase only VM 102 scsi0
(local-lvm:vm-102-disk-1) from 100 to 128 GiB through an exact saved-plan guard.
Keep the 1,200-GiB scsi1 data disk and all control-plane disks unchanged.
Total primary allocations become 1,428 GiB, plus two EFI volumes. Preserve
StrictFIFO budgets and 60-GiB scratch plus 8-GiB headroom. Verify physical pool
headroom before allocation, keep AI Off and drain compute before a graceful
worker reboot if required. Talos EPHEMERAL uses grow:true on the system disk.
Verify filesystem/partition identity preservation, larger measured capacity,
Ready nodes, Pi-hole UDP/TCP and no leaked reservations; then repeat the cache
image-inclusive checks. Never shrink a disk as rollback.

## Nested Docker resource containment repair (2026-09-16)
Runtime inspection found stock buildx creating its builder under `/docker/buildx`,
outside the admitted runner Pod. The prior Pod CPU/RAM sample excluded that
builder, so it cannot qualify any measured allocation. Preserve the original
observation in `evidence/nested-cgroup-defect-20260916.json`.

The Docker sidecar now derives and validates the guaranteed Pod cgroup against
its downward-API UID and uses that parent for ordinary Docker containers. The
Talos build-cache action passes the same validated parent explicitly to buildx,
which otherwise overrides the daemon default. Both paths share the existing
4-CPU/16-GiB aggregate Pod limit; approved resource budgets are unchanged. The
repair was deployed using a fresh guarded plan and verified with a fresh empty
post-plan. Runtime ancestry evidence is in
`evidence/cgroup-deployment-20260916-05.json`.

The temporary read-only administration observer in `scripts/ci_measure.py` and
`scripts/ci_pod_usage.py` is preliminary measurement tooling. Samples explicitly
do not qualify job sizing until full lifecycle coverage, image accounting and
upstream byte observations are established. No measured budget is adopted by
this repair. Stock BuildKit retry-count acceptance does not waive resource
containment, integrity checks or any remaining runtime acceptance.

## Concurrency revision authorized 2026-09-16
The user requested doubling shared compute scratch from 60 to 120 GiB and
reducing per-job reservations. They explicitly selected provisional limits, then
fresh-run validation and refinement. Retain 33.5 CPU / 150 GiB, 4 CPU / 18 GiB
platform reserve, 8 GiB storage headroom and the separate 64-GiB Nexus allocation.
The current 128-GiB worker OS disk cannot contain the doubled pool alongside
images and reserves. Expand only VM 102 scsi0 from 128 to 192 GiB through a fresh
exact saved-plan guard, fresh physical thin-pool verification and drained worker
maintenance. Preserve scsi1 and all retained filesystem identities.

Deploy provisional Docker configurations at 4 CPU / 16 GiB with 12 GiB for
smaller Docker jobs and 24 GiB for image builds. Keep the compatible 30-GiB
configuration for the largest builds and the existing non-Docker configurations.
Deploy catalog entries before workflows reference them. Enforce whole-Pod
budgets, including nested Docker/BuildKit cgroups. Configure two Docker layer
download attempts: the interrupted registry fixture demonstrates byte-range
resume on attempt two, while the original one-attempt setting fails with EOF.
This preserves the two-cache/three-upstream ceiling and does not extend the
separate BuildKit retry exception. Deployment, fresh job success, concurrency
and final acceptance remain unverified until new runtime evidence exists.

## Direct LAN reconciliation, 2026-09-16
The user removed the laptop hop and confirmed Proxmox `10.0.0.92`, Talos nodes
`10.0.0.220`/`10.0.0.222` and API VIP `10.0.0.231`. Operational configuration
and recovery use these addresses. Preserve the existing four Tailscale host
routes rather than advertising the full LAN. Retired laptop DHCP/NAT mutation
commands refuse execution. Historical receipts retain their original addresses.
Live authenticated VIP readiness and both Ready nodes are verified; guarded
plans must reconcile the new desired network before deployment.
