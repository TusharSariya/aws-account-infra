## 1. Foundation
- [x] 1.1 Revise OpenSpec and preserve superseded evidence; strict validation passes.
- [x] 1.2 Implement independent hosted and Mac bootstrap/recovery with saved-plan guards and existing approval gates.
- [x] 1.3 Implement exact VM 103 retirement guard, DHCP/permission cleanup and graceful 172-GiB worker maintenance.
- [x] 1.4 Verify worker allocatable, platform reservations and Pi-hole recovery before enabling the historical 36 CPU / 160 GiB pool; revised budgets require task 5.8.

## 2. Admission and runners
- [x] 2.1 Pin and verify Kueue 0.19.4 and ARC 0.14.2 Helm artifacts in the independent homelab-ci state root.
- [x] 2.2 Implement shared StrictFIFO quota, equal priorities, no borrowing/preemption and oversized-request rejection.
- [x] 2.3 Integrate lifecycle-owned AI Pods and queue status while preserving Stop, Force Stop, idle and storage behavior.
- [x] 2.4 Integrate Argo execution Pods with execution-only deadlines and exempt operational Pods.
- [x] 2.5 Configure disposable 4 CPU / 16 GiB / 30 GiB ARC runners and privately enroll the existing repository GitHub App.
- [x] 2.6 Verify admission enforcement and platform/operational availability during Kueue outage.

## 3. Cutover and acceptance
- [x] 3.1 Implement explicit CI_EXECUTOR routing while keeping bootstrap/recovery hosted and forks disabled.
- [x] 3.2 Verify real checkout, Docker, ARM packaging, privileged disposable quotas and private deployments on ARC.
- [x] 3.3 Verify AI-first/CI-first, strict FIFO, CPU/RAM exhaustion and observed reservation release.
- [ ] 3.4 Verify queued cancellation, controller/node restart and cleanup without leaks.
- [x] 3.5 Prove hosted recovery with ARC absent and Stop/Status/Pi-hole during queue exhaustion/outage.
- [ ] 3.6 Record fresh empty post-deployment plans, successful required GitHub checks and three reviewed PRs; enable Talos routing only after acceptance.

## 4. Multiple job-sized runners (supersedes the one-runner restriction)
- [x] 4.1 Update specifications and generate catalog-driven scale sets with exact rendered Pod budgets, compatibility state migration and validation of arbitrary sizes, unknown names and oversized budgets.
- [x] 4.2 Add shared scratch admission and fail-closed measured storage/listener/Pod-slot checks; verify CEL storage exhaustion and preserved operational bypass.
- [x] 4.3 Audit and implement job-specific routine routing, reusable jobs and supporting gates with only required prerequisites; preserve hosted exceptions and affected-state selection.
- [x] 4.4 Deploy catalog and storage admission through the guarded CI root after runners become idle; record fresh empty plan.
- [x] 4.5 Observe simultaneous mixed-size ARC runners, CPU/RAM/scratch exhaustion, StrictFIFO and release after completion/cancellation.
- [x] 4.6 Complete actual checkout, scanners, LocalStack, Docker publication, ARM packaging/upload, SDK and guarded application-only private deployment proofs on ARC.
- [x] 4.7 Complete AI-first/CI-first contention, controller/node restart and cleanup, full-queue/outage Stop/Status/Pi-hole and independent hosted recovery proofs.
- [x] 4.8 Record the user waiver dated 2026-09-15 (America/St_Johns) for independent 24-hour GitHub expiry observation. Expiry remains unverified; optional tooling is retained and must not be run for this rollout.
- [ ] 4.9 Merge validated routing, set CI_EXECUTOR=talos and verify representative routine workflows at declared sizes without leaked reservations.
- [ ] 4.10 Record final empty plans, autostart recovery, Pi-hole health and AI Off; verify ordinary workflows need no paid hosted compute before restoring the temporary Actions budget to $0.

## 5. Shared local cache and measured scratch (2026-09-15)
- [x] 5.1 Update the design and requirements with approved Nexus storage/resource budgets and preserve prior evidence, including authorized EULA and UI cleanup setup exception.
- [x] 5.2 Deploy revised admission/AI budgets and isolated Nexus/PostgreSQL services through guarded OpenTofu after actual XFS quotas, retained PV commitments, thin-pool headroom and image-inclusive 60-GiB scratch checks pass.
- [x] 5.3a Deploy and reconcile the initial proxy/raw/build repositories, authorized EULA and separate read-only consumer/build-writer/monitor roles; verify successful monitoring execution.
- [ ] 5.3b Reconcile all workflow origins/distributions; preview and configure supported cleanup (14 days dependencies, 30 days pinned raw, 7 days build caches), daily cleanup and subsequent compaction; verify UI settings and execution and exercise warning delivery.
- [ ] 5.4 Build reviewed pinned prerequisite runner images; route package managers and nested Docker through cache with verified bounded upstream fallback and nonfatal upload failure.
- [x] 5.5 Disable explicit GitHub dependency/build cache access, audit nested composite/setup actions, and verify repository 10-GB free allowance and $0 paid cache-storage budget with further usage blocked.
- [ ] 5.6 Measure eligible jobs cold and twice warm on fresh runners, adopt max plus 25% and 1 GiB rounded up with 2-GiB minimum only after revalidation at the declared size.
- [ ] 5.7 Prove fresh-runner npm/Python/APT/Docker reuse with upstream bytes/time, concurrent mixed sizes, actual quota rejection, cleanup/compaction, interrupted downloads, cache/node restart and fallback.
- [ ] 5.8 Repeat revised-budget AI-first/CI-first, FIFO, cancellation and cleanup, Stop/Status/Pi-hole under full queue and Kueue outage, plus hosted recovery.
- [ ] 5.9 Complete remaining original acceptance with independent 24-hour expiry explicitly waived and unverified; only then enable global Talos routing and verify empty plans, AI Off, Pi-hole and no reservations.

## 6. Authorized OS capacity prerequisite
- [x] 6.1 Implement and verify the exact VM 102 scsi0 100-to-128-GiB saved-plan guard; preserve scsi1, control-plane disks and all other VM settings.
- [x] 6.2 Apply the guarded expansion, verify Talos EPHEMERAL growth and retained filesystem identities, recover Ready/Pi-hole/AI Off and rerun fresh image-inclusive capacity checks.
