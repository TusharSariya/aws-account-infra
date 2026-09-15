# Kueue migration implementation evidence

## 001 - Local implementation, 2026-09-14

- Operator: Codex; target: isolated worktree `/private/tmp/aws-account-infra-kueue`, based on committed `695c495`.
- Action: implement foundation, Kueue/ARC integration and gated routine routing. The original checkout and the prior agent's dirty CI worktree were not modified.
- Artifacts: fetched Kueue 0.19.4 and ARC controller/scale-set 0.14.2 OCI charts; archive SHA-256 hashes recorded in `config/environments/kubernetes/homelab-ci/artifacts.json`. Verified runner/Docker manifests and pinned their digests. Helm output confirms full Pod requests/limits of 4 CPU / 16 GiB.
- Local validation: strict OpenSpec; OpenTofu CI-root init/validate and Proxmox mocked plans (5); lifecycle tests (62); queue/foundation/rendering/guard tests (10); existing CI plan guard tests (10); deployment-unit tests (20); 14 CEL behavior cases using Kubernetes v0.36.3 libraries; actionlint, changed-shell ShellCheck and gitleaks (no leaks).
- Actual local ARM execution: built the pinned ARM Linux packaging container under OrbStack, verified `aarch64`, and passed 32 Lambda tests. This is local evidence, not ARC/GitHub success or a packaging upload.
- Retained failed attempts: initial lifecycle chart test lacked the pinned Argo archive in the new worktree; fetching verified application artifacts corrected it. Local Helm 4 does not accept Helm 3 executable postrenderer flags, so local render verification piped manifests through the identical postrenderer. OpenTofu's Helm 3 provider configuration validates. Initial Go CEL build required an unaccepted Xcode license via cgo; rerunning the pure-Go check with `CGO_ENABLED=0` passed without changing license acceptance.
- Runtime state: no infrastructure apply, worker shutdown, VM deletion, DNS/ACL change, secret enrollment or CI_EXECUTOR change was performed. AI was not started. No live acceptance task is credited by these checks.
- Rollback: leave routine routing hosted; use reviewed source and original independent Mac/hosted recovery. Never remove workload finalizers to simulate released quota. Retain private saved-plan records and failures before retrying.

## 002 - Review corrections, 2026-09-14

- Standards axis: no documented-standard violations; one operational coupling finding. Removed artifact/registry setup from read-only status and credential enrollment. Added a status-without-registry regression test.
- Spec axis: one P1 integration finding. Off-state template adoption could remove Kueue's Deployment/Pod metadata while the outage-safe webhook filter skipped re-injection. The approved template now explicitly carries the pinned `kueue.x-k8s.io/pod-suspending-parent: deployment` annotation and managed label. Added a regression using the rendered template across Off, Start, Stop and second Start. Actual cluster workload creation/admission remains an unchecked runtime acceptance step.
- Also pinned Kueue and ARC controller image digests after registry manifest verification. The Helm chart archives were already checksum-pinned.

- Retirement now checks that AI is explicitly Off with zero runtime Pods before either planning or applying; a regression covers desired state, replica and Pod rejection. The combined test invocation initially omitted `PYTHONPATH=scripts`; rerunning with the repository script path passed.

- Pre-push caught inherited OpenTofu test formatting and a root-default ARM packaging image. Corrected formatting, added a non-root image user and run-time caller UID/GID mapping, then repeated ARM execution and the push checks.

- The Docker gitleaks hook could not resolve linked-worktree metadata and misleadingly reported zero commits scanned. Added a read-only shared Git metadata mount so the hook scans actual history; the separate native scan already passed.

## 003 - Authorized Mac rollout, 2026-09-15

- User explicitly authorized the staged Mac rollout. Existing credentials, cluster identity and App/key reused; AI remains Off and the ordinary schedule suspended.
- VM 103 passed identity checks and was gracefully stopped. Guarded retirement applied its deletion and worker configuration 156 -> 172 GiB, then failed deleting the exact pinned image with HTTP 403 `Datastore.Allocate`. Failed receipt/log retained under `~/.config/aws-account-infra/kueue/retirement-20260915-01/`.
- Added narrowly scoped recovery: verify failed original saved plan, check VM absence and worker configuration, verify exact image path/checksum, delete only that image via the existing root SSH connection, require an empty hardware plan. No provider privileges were widened. First recovery post-plan omitted the existing approval variable and failed its precondition; preserved that attempt, corrected it and verified the second post-plan empty. Dedicated CI ACL grants removed; shared identities retained.
- Worker gracefully restarted with a new boot, Proxmox confirms 172 GiB, Kubernetes Ready. Pi-hole rollout and UDP/TCP queries recovered. Kubernetes reports capacity 168.92 GiB and allocatable 168.44 GiB, below the planned 160 + 10 GiB budget. Pool installation held for an explicit budget decision. Observed platform requests 0.70 GiB, Pod working set 1.81 GiB, node working set 1.99 GiB.
- Router sudo requires interactive authentication. Prepared a private one-stage cleanup wizard; DHCP removal not credited until verified.

- The maintenance helper timed out because its >=170-GiB capacity assumption rejects the actual 168.92-GiB capacity. Proxmox effective RAM is exactly 172 GiB, boot ID changed, Ready and DNS were independently verified in private `rollout-20260915-01/recovery-observation.json`; the helper receipt remains unsuccessful.
- Application planning from the cutover revision correctly failed image-input provenance because routine image workflow routing changed. Planning from the exact admission PR revision in `/private/tmp/aws-account-infra-kueue-admission-deploy` passed existing remote image receipts and saved-plan guards: only AI, lifecycle and jobs releases update. No application apply occurred. This respects the ordered rollout and does not weaken image provenance.

## 004 - Resume CI rollout, 2026-09-15

- User approved the 8-GiB platform reserve after checks. Updated the reserve and the maintenance capacity assumption; regression covers actual 168.44-GiB allocatable accepting 160+8 and rejecting 160+10. Eleven queue/foundation tests pass.
- Router CI reservation is confirmed absent and existing Talos DHCP reservations preserved. During recheck the Proxmox host had just rebooted and both Talos VMs were stopped (autostart disabled). Verified exact VM identities and started existing control-plane and worker VMs. User explicitly requested autostart after CI is fixed; leave that ordered follow-up pending.
- CI bootstrap now retains failed command output and apply logs privately to preserve real rollout failure evidence.

- CI releases are installed through guarded saved plans; `ci-20260915-04` has a fresh empty post-plan. All initial failures retained: Mac MagicDNS resolution (fixed via exact Tailscale peer lookup), cohort-only borrowing/lending fields and unsupported priority globalDefault field (removed, live server schema verified), and Helm's failed unrecorded queue release (imported exact existing release into its state, then upgraded).
- ARC startup replaced the initial EphemeralRunnerSet while the listener still referenced it. Normal deletion/recreation of only the stale listener restored its link to the current set; listener authenticates to GitHub and polls with zero idle runners. Added explicit listener security context. CEL static checking could not infer the Pod overhead map; explicit dyn access retains overhead accounting without type warnings.
- First FIFO fixture had identical second-resolution creation timestamps for the older/later pair. Preserved failure and automatic cleanup, separated timestamps, and reran CPU acceptance successfully: older-large blocks newer-small, cancellation and normal completion release quota, all test Pods/Workloads removed.
- Applied AI/lifecycle/jobs from the exact admission revision using the independent local saved-plan workflow and existing remotely verified image receipts. Intentional AI Off verified.
- The ARC acceptance workflow is not yet on the default branch, so dispatch correctly returned 404. Added an explicitly labeled same-repository PR acceptance trigger retaining prod and fork restrictions; no routine routing variable changed.

## 005 - Live queue and outage acceptance, 2026-09-15

- Separate CPU and RAM FIFO fixtures pass, including cancellation, normal completion and cleanup. Live admission rejects oversized CPU/RAM and missing-queue compute; accepts valid queued compute and operational Pods.
- The first real ARC request exposed an omitted resource: Kueue also accounted for the runner's declared ephemeral storage. Explicitly excluded ephemeral-storage from Kueue quota while retaining Kubernetes requests/limits and the 30-GiB scratch bound. CI attempt 05 applied successfully with a fresh empty plan; the same pending workload survived the controller restart and was admitted.
- With ARC holding 4 CPUs, AI Start remained Starting/Pending at queue position 1 with its full 35.75-CPU / 77-GiB request and zero idle time. Stop cancelled it and termination was observed. Exact Tailscale peer resolution now makes the authenticated operator CLI independent of Mac MagicDNS; credentials pass over stdin, not command arguments.
- Briefly stopped Kueue. Status/Stop worked, an operational command Pod completed, Pi-hole answered UDP/TCP, and ordinary compute admission failed closed. Finally restored Kueue to one healthy replica and verified AI Off with no runtime Pods. Private receipt: ci-20260915-05/outage-result.json. This completes task 2.6, not hosted-recovery or full contention acceptance.
- ARC marked the first runner Outdated and removed its scale set before accepting a job. The pinned ARC 0.14.2 controller maps runner exit code 7 to deprecated software. Updated only the runner image from 2.333.0 to GitHub's current 2.337.0, verifying the multi-platform registry digest. CI attempt 06 changes only the runner release and has a fresh empty post-plan. Real GitHub job acceptance remains pending until observed.
- User also requires automatic startup of essential Kubernetes services, including Pi-hole, and Talos VMs after CI repair. Existing platform Deployments recovered automatically during the observed host recovery and remain outside workload admission. VM boot flags are still pending that ordered follow-up.

- Real run 34954804042 accepted on the updated Talos runner and checkout passed, then tool setup failed: Ubuntu noble has no apt installation candidate for awscli. Replaced that dependency with AWS CLI 2.36.45's official x86_64 archive and its verified SHA-256. Failed job Pod and all queue reservations cleaned up normally. Retain this run as failure evidence; rerun must prove the remaining steps.
