# Measured CI continuation - 2026-09-15 America/St_Johns

Fresh worktree `/private/tmp/aws-account-infra-finish-measured-ci`, branch
`feat/finish-measured-ci`, from main `d99c04a991d89badc8a3c3e73c823dcd9c090d58`.
Original checkout and other worktrees are preserved. Runtime timestamps are UTC.

## Reconciled merge and hosted evidence

GitHub API readback confirms:
- PR #80 merged 2026-09-16T01:11:09Z as `3fb461e1d198175a3ed97f4873053a4eefa1f605`.
- PR #81 merged 2026-09-16T01:55:11Z as `d99c04a991d89badc8a3c3e73c823dcd9c090d58`.
- Successful plan run [35045446781](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/35045446781).
- Successful admission contracts/admission run [35045446662](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/35045446662).
- Successful apply run [35045536670](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/35045536670), including isolated storage and capacity/network/lifecycle/PVC acceptance jobs. Maintenance jobs were skipped.
- Main image runs Ollama [35045959271](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/35045959271), Odysseus [35045959198](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/35045959198), and Lambda [35045959230](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/35045959230) succeeded. These run conclusions do not replace artifact/input-hash verification.

Disk expansion, quota-basename correction and verified AI PR image receipts remain
in `nexus-cache-20260915.md`. Its failures are preserved. Historical 36 CPU/160 GiB
acceptance does not verify revised 33.5 CPU/150 GiB contention.

## Explicit waiver

The user waived independent 24-hour GitHub expiry observation on 2026-09-15.
Expiry remains unverified. No expiry fixture was dispatched. Optional tooling is
retained. Cancellation, controller/node restart and reservation cleanup remain
required. Corrected the erroneous 118-GiB requirement to 18 GiB.

## Deployment and recovery

Private guarded receipts: `~/.config/aws-account-infra/kueue/nexus-finish-20260915-01`
through `-03`. All plans used fresh capacity checks and the existing CI backend.
The first apply updated the queue and started Nexus/PostgreSQL. Its configuration
hook failed after EULA, repositories and roles, before user reconciliation.
The running Nexus OpenAPI schema requires `emailAddress` for creation and `source`
for updates; the original code used `email` and omitted `source`. A regression test
failed against the original reconciler and passed after correction.

The failed initial install was absent from OpenTofu state. The second attempt
failed with `cannot re-use a name that is still in use`. Retained both failures.
Backed up state privately, then used a temporary declarative import of exactly
`helm_release.cache = homelab-cache/homelab-cache` with the guarded saved plan.
The third attempt imported/updated only the cache release, passed its hook and
produced an empty post-apply plan. The temporary import file is retained privately
and removed from repository configuration so clean bootstrap remains possible.
No release or retained volume was deleted.

`nexus-deployed-20260915.json` records fresh capacity, revised queue resources,
AI replicas/requests, empty reservations and successful monitor output. Both
service Pods are Ready. API readback verifies anonymous has only cache-reader,
the build writer only cache-build-writer, and metrics user only cache-monitor.
A monitor execution after configuration succeeded with zero usage and no warnings;
earlier authentication failures remain in Kubernetes history. This does not prove
warning delivery at an actual threshold or cache reuse.

## Billing and local work

GitHub readback: `max_cache_size_gb=10`; repository budget
`9acefd2e-31d9-474f-82e7-be3edeb44c22` is `actions_cache_storage`, amount 0,
`prevent_further_usage=true`. The temporary organization Actions product budget
remains $5 pending ordinary Talos execution. CI_EXECUTOR is absent, retaining the
explicit hosted default. No automatic paid fallback was introduced.

The cache audit now includes composite actions and setup-node/setup-python cache
inputs as well as uv, Go and GitHub cache actions. The sizing helper requires
complete same-revision/image/job/platform measurements, whole-Pod coverage before
checkout through cleanup, CPU/RAM/upstream/time fields and cold-content evidence.
The fourth distinct runner must have comparable measurements and stay within its
declared scratch limit. No measurements or smaller catalog entries were invented.
`job-inventory-20260915.json` lists 64 jobs/variants, including hosted exceptions
and explicitly unresolved dynamic deployment selection.

## Remaining blocker and acceptance

Chrome rejected UI automation because another extension panel is open. The user
was asked to dismiss it. Cleanup policies/schedules/previews and compaction remain
unconfigured and unverified. Client wiring, prerequisite images, cold/twice-warm
measurements, fourth-run validation, failure/restart/contention proofs and global
routing remain open. OpenSpec is not complete and must not be archived.

## Verification at pause

- 85 focused local Python tests passed across cache, capacity, Kueue, runner and deploy-unit checks.
- Runner catalog/HCL whole-Pod validation, CI-root OpenTofu validation, strict OpenSpec and whitespace checks passed.
- A fresh guarded plan after removing the temporary import has no changes; private receipt `nexus-finish-20260915-04`, sanitized capacity in `nexus-final-plan-20260915.json`. Its preflight again verified Pi-hole UDP/TCP, AI Off and idle runners.
- The manually triggered successful monitoring Job was removed after its receipt was captured. The scheduled monitor and historical failed observations remain.
- OpenSpec progress is 28/38 tasks complete. Local checks are not claimed as hosted checks for this branch. No merge, routing cutover or Actions compute-budget reset was performed.
