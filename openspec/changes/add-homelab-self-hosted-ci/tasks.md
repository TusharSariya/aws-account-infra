## 1. Foundation
- [x] 1.1 Revise OpenSpec and preserve superseded evidence; strict validation passes.
- [x] 1.2 Implement independent hosted and Mac bootstrap/recovery with saved-plan guards and existing approval gates.
- [x] 1.3 Implement exact VM 103 retirement guard, DHCP/permission cleanup and graceful 172-GiB worker maintenance.
- [x] 1.4 Verify worker allocatable, platform reservations and Pi-hole recovery before enabling the 36 CPU / 160 GiB pool.

## 2. Admission and runners
- [x] 2.1 Pin and verify Kueue 0.19.4 and ARC 0.14.2 Helm artifacts in the independent homelab-ci state root.
- [x] 2.2 Implement shared StrictFIFO quota, equal priorities, no borrowing/preemption and oversized-request rejection.
- [x] 2.3 Integrate lifecycle-owned AI Pods and queue status while preserving Stop, Force Stop, idle and storage behavior.
- [x] 2.4 Integrate Argo execution Pods with execution-only deadlines and exempt operational Pods.
- [x] 2.5 Configure disposable 4 CPU / 16 GiB / 30 GiB ARC runners and privately enroll the existing repository GitHub App.
- [x] 2.6 Verify admission enforcement and platform/operational availability during Kueue outage.

## 3. Cutover and acceptance
- [x] 3.1 Implement explicit CI_EXECUTOR routing while keeping bootstrap/recovery hosted and forks disabled.
- [ ] 3.2 Verify real checkout, Docker, ARM packaging, privileged disposable quotas and private deployments on ARC.
- [ ] 3.3 Verify AI-first/CI-first, strict FIFO, CPU/RAM exhaustion and observed reservation release.
- [ ] 3.4 Verify queued cancellation, GitHub expiry, controller/node restart and cleanup without leaks.
- [ ] 3.5 Prove hosted recovery with ARC absent and Stop/Status/Pi-hole during queue exhaustion/outage.
- [ ] 3.6 Record fresh empty post-deployment plans, successful required GitHub checks and three reviewed PRs; enable Talos routing only after acceptance.

## 4. Multiple job-sized runners (supersedes the one-runner restriction)
- [x] 4.1 Update specifications and generate catalog-driven scale sets with exact rendered Pod budgets, compatibility state migration and validation of arbitrary sizes, unknown names and oversized budgets.
- [x] 4.2 Add shared scratch admission and fail-closed measured storage/listener/Pod-slot checks; verify CEL storage exhaustion and preserved operational bypass.
- [x] 4.3 Audit and implement job-specific routine routing, reusable jobs and supporting gates with only required prerequisites; preserve hosted exceptions and affected-state selection.
- [x] 4.4 Deploy catalog and storage admission through the guarded CI root after runners become idle; record fresh empty plan.
- [ ] 4.5 Observe simultaneous mixed-size ARC runners, CPU/RAM/scratch exhaustion, StrictFIFO and release after completion/cancellation.
- [ ] 4.6 Complete actual checkout, scanners, LocalStack, Docker publication, ARM packaging/upload, SDK and guarded application-only private deployment proofs on ARC.
- [ ] 4.7 Complete AI-first/CI-first contention, controller/node restart and cleanup, full-queue/outage Stop/Status/Pi-hole and independent hosted recovery proofs.
- [ ] 4.8 Observe the full GitHub 24-hour request expiry separately from cancellation with external monitoring and fixture cleanup.
- [ ] 4.9 Merge validated routing, set CI_EXECUTOR=talos and verify representative routine workflows at declared sizes without leaked reservations.
- [ ] 4.10 Record final empty plans, autostart recovery, Pi-hole health and AI Off; verify ordinary workflows need no paid hosted compute before restoring the temporary Actions budget to $0.
