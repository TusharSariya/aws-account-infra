## Why
Application compute needs one bounded admission pool on the existing Talos worker. GitHub-hosted bootstrap and Mac recovery must remain independent of that pool.

## What Changes
- Replace the separate VM runner proposal with pinned Kueue 0.19.4 and ARC 0.14.2.
- Restore worker RAM to 172 GiB and admit AI, CI and ordinary Argo Pods against one 33.5 CPU / 150 GiB pool.
- Add reviewed arbitrary-size runner catalog, multiple disposable scale sets, whole-Pod validation and shared 60-GiB scratch admission with measured capacity gates.
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
download clients. Preserve the 60-GiB compute scratch
plus 8-GiB headroom gate and all original migration acceptance. The user permits
UI-managed cleanup schedules with verification where the CE REST API is unavailable.

## Authorized worker OS disk expansion
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
