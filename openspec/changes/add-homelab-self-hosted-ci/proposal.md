## Why
Application compute needs one bounded admission pool on the existing Talos worker. GitHub-hosted bootstrap and Mac recovery must remain independent of that pool.

## What Changes
- Replace the separate VM runner proposal with pinned Kueue 0.19.4 and ARC 0.14.2.
- Restore worker RAM to 172 GiB and admit AI, CI and ordinary Argo Pods against one 33.5 CPU / 150 GiB pool.
- Add reviewed arbitrary-size runner catalog, multiple disposable scale sets, whole-Pod validation and shared 120-GiB scratch admission with measured capacity gates.
- Preserve lifecycle controls, retained AI storage, reviewed workflows and deployment gates.
- Retire only identified VM 103 CI resources through guarded maintenance.
- Select routine execution explicitly with CI_EXECUTOR=github-hosted|talos after acceptance; no automatic paid fallback.

## Capabilities
### New Capabilities
- `homelab-self-hosted-ci`: shared compute admission and disposable Talos runners.
### Modified Capabilities
None. Existing AI lifecycle controls remain authoritative.

## Impact
Three reviewed PRs: foundation, admission/runners, cutover. New state key: kubernetes/homelab-ci/terraform.tfstate. Existing roots and keys remain intact. The prior plan and completed checkboxes are preserved in evidence/pre-kueue-plan; they do not prove this migration.

## Local cache extension, 2026-09-15
Add bounded worker-local Nexus Community Edition and PostgreSQL: 64 GiB XFS
storage (48 content, 6 database, 2 configuration, 8 temporary/logs), within a revised
4 CPU / 18 GiB platform reserve. AI uses 33.25 CPU / 77 GiB only when admitted.
Replace remote dependency/build caches with shared proxy/raw/hosted cache
repositories, measured job-specific scratch, pinned prerequisites, bounded verified
upstream fallback and supported cleanup. On 2026-09-16 the user accepted stock
BuildKit's internal excessive registry retries for now; the exact two-cache/
three-upstream attempt limit remains required for other dependency and pinned
download clients. Preserve the 120-GiB compute scratch
plus 8-GiB headroom gate and all original migration acceptance. The user permits
UI-managed cleanup schedules with verification where the CE REST API is unavailable.

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

## Acceptance waiver, 2026-09-15 (America/St_Johns)
The user waived the independent 24-hour GitHub expiry observation. It remains
unverified; retain optional expiry tooling without running it. Cancellation,
controller/node restart and reservation-cleanup tests remain mandatory. This
waiver does not complete cache, sizing or routing acceptance.

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
