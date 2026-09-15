## 1. Foundation
- [x] 1.1 Revise OpenSpec and preserve superseded evidence; strict validation passes.
- [x] 1.2 Implement independent hosted and Mac bootstrap/recovery with saved-plan guards and existing approval gates.
- [x] 1.3 Implement exact VM 103 retirement guard, DHCP/permission cleanup and graceful 172-GiB worker maintenance.
- [ ] 1.4 Verify worker allocatable, platform reservations and Pi-hole recovery before enabling the 36 CPU / 160 GiB pool.

## 2. Admission and runners
- [x] 2.1 Pin and verify Kueue 0.19.4 and ARC 0.14.2 Helm artifacts in the independent homelab-ci state root.
- [x] 2.2 Implement shared StrictFIFO quota, equal priorities, no borrowing/preemption and oversized-request rejection.
- [x] 2.3 Integrate lifecycle-owned AI Pods and queue status while preserving Stop, Force Stop, idle and storage behavior.
- [x] 2.4 Integrate Argo execution Pods with execution-only deadlines and exempt operational Pods.
- [ ] 2.5 Configure disposable 4 CPU / 16 GiB / 30 GiB ARC runners and privately enroll the existing repository GitHub App.
- [ ] 2.6 Verify admission enforcement and platform/operational availability during Kueue outage.

## 3. Cutover and acceptance
- [x] 3.1 Implement explicit CI_EXECUTOR routing while keeping bootstrap/recovery hosted and forks disabled.
- [ ] 3.2 Verify real checkout, Docker, ARM packaging, privileged disposable quotas and private deployments on ARC.
- [ ] 3.3 Verify AI-first/CI-first, strict FIFO, CPU/RAM exhaustion and observed reservation release.
- [ ] 3.4 Verify queued cancellation, GitHub expiry, controller/node restart and cleanup without leaks.
- [ ] 3.5 Prove hosted recovery with ARC absent and Stop/Status/Pi-hole during queue exhaustion/outage.
- [ ] 3.6 Record fresh empty post-deployment plans, successful required GitHub checks and three reviewed PRs; enable Talos routing only after acceptance.
