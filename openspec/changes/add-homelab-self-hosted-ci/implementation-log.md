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

## 006 - Automatic platform startup and remaining ARM issue, 2026-09-15

- Updated both Talos VM boot flags through the exact saved OpenTofu plan. Only on_boot false -> true changed for VM 100 and VM 102; fresh hardware plan is empty. Proxmox readback confirms onboot=1 and startup orders 1/2. No VM reboot occurred. Private receipt: autostart-20260915-02/receipt.json. First plan failed Mac MagicDNS and is retained; retry used an exact-peer local CONNECT tunnel preserving the original hostname and TLS verification.
- Pi-hole remains one desired/available replica without queue labels. Its automatic controller recovery after the earlier host restart and availability through the Kueue outage are observed.
- Retry 34956404522 passed runner startup, checkout, pinned AWS CLI installation and uv setup. QEMU setup failed because the Talos worker lacks binfmt_misc: cannot mount filesystem, no such device. No ARM or private-deployment acceptance is credited. The supported Talos extension requires an explicit OS maintenance path; ordinary Talos changes retain no_reboot.

- Prepared `docs/homelab-ci-arm-maintenance.md` with the exact three-extension schematic and worker-only maintenance/recovery scope. Image Factory accepted the schematic, but installer manifest retrieval has not completed; a separate 20-second HEAD request timed out. The new installer digest is not verified and no extension/configuration/OS upgrade has been applied.

## 007 - ARM worker extension recovery, 2026-09-15

- Image Factory eventually returned the verified installer index e5e30232d1069b02db72e5b0e9d502cad7dc13b7af2cb3e087a244550291be10. Updated only the worker recovery installer/module configuration, keeping Talos v1.13.9, original bootstrap ISO and all retained storage. Generated private configuration passed strict validation and drift self-tests.
- Added a dedicated saved-maintenance helper. Standards/Spec reviews identified diagnostic retention and storage identity checks; corrected them, including rejecting changed identities before mutation. Four identity regression tests pass; both reviewers report no remaining blocking findings.
- Attempt 03 staged the exact worker-only patch but upgrade failed before reboot: Talos pulled the digest-only image reference then looked up the tag-plus-digest reference. Failed receipt/log retained. Attempt 04 used the same immutable digest in canonical form and completed a graceful worker power cycle.
- Successful receipt verifies new boot, all three extensions, binfmt_misc loaded, both boot flags enabled, unchanged effective 172-GiB RAM, exact Proxmox data disk, PV identities/specs, data filesystem/partition UUIDs, mounted XFS project quotas, Kueue/ARC readiness and Pi-hole UDP/TCP. AI stayed Off; compute was quiescent with no leaked reservations. Ordinary no_reboot OpenTofu resources remain unchanged.
- Reran real ARC acceptance 34956404522, attempt 2, after extension recovery. Remaining steps receive credit only when observed.

- Fresh Talos planning initially failed because the isolated checkout lacked the pinned Cilium archive. After verified tool/chart setup, its only change was the worker configuration hash. A live no-reboot dry-run showed no configuration diff; the authorized Mac saved-plan reconciliation updated only that hash, and the fresh Talos plan is empty. Private receipt: talos-post-arm-20260915-01/local-reconcile.json. Failed/incomplete Talos plans are now explicitly rejected by the guard; regression added. Twenty-five Talos tests pass.
- ARC attempt 2 has passed checkout, tool setup, QEMU registration, Buildx and the privileged bounded Docker fixture. ARM and private networking remain in progress at this checkpoint.

- Argo independent-smoke entered the argo LocalQueue, was admitted alongside CI, completed, and its Workflow/Pod/Workload cleanup was observed. Private admission/completion evidence: ci-20260915-06/argo-proof.json.
- ARC attempt 2 built the ARM image but Docker execution failed with exec format error. QEMU's temporary container mounted and unmounted binfmt_misc; without a lasting mount, its registrations disappeared. CI attempt 07 updates only the disposable DinD startup to keep that filesystem mounted for the Pod lifetime, preserving all resources and no host mounts. Fresh CI post-plan is empty. Added early actual ARM execution to acceptance and disabled unnecessary pip bytecode compilation during emulated image construction.
