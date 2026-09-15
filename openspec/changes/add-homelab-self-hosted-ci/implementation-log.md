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
