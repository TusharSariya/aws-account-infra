# Job-sized runner implementation and deployment, 2026-09-15

## Scope and source

Worktree: `/private/tmp/aws-account-infra-sized-runners`, branch
`feat/job-sized-kueue-runners`, based on merged PR #79 (`6a2d681`). The original
planning checkout and its uncommitted work were preserved. Existing evidence
remains authoritative for earlier observations; this entry does not replace it.

## Local verification

- 18 Kueue unit/contract tests passed, including actual pinned ARC Helm rendering
  of all catalog configurations and arbitrary 3.001-CPU Docker budget splitting.
- 15 CEL cases passed, including CPU, memory and scratch oversized rejection,
  restartable-init accounting, operational bypass and privileged gate removal.
- 23 affected-state selection tests and 5 relevant-check selection tests passed.
- OpenTofu validation/formatting, actionlint with ShellCheck, strict OpenSpec and
  whitespace checks passed. These are local results, not GitHub check evidence.

## Guarded deployment

The existing Mac recovery/administration path applied the exact saved CI-root
plan through `scripts/homelab-ci.py`. The plan updated Kueue/queue, moved the
existing runner state address without replacing the release, and created the
light/checks scale sets. No deletions or other state roots were included.

Private immutable plan, kubeconfig, execution receipt and post-plan are under
`~/.config/aws-account-infra/kueue/sized-runners-20260915-01/`. Credentials and plan
contents are intentionally not committed. The receipt records successful apply
and `post_plan_empty=true`.

Observed preflight: worker allocatable 37.95 CPU, 176626296 KiB RAM and
94227975217 bytes ephemeral storage; projected platform requests 1.056 CPU,
1358954496 bytes RAM; root/image used 19076153344 bytes (images included in root
usage); 8-GiB additional storage headroom; 22 projected platform Pods, 30 maximum
catalog runner slots and 10 additional Pod slots within the node's 110 limit.
AI termination and Pi-hole TCP/UDP DNS passed before plan and apply.

Observed after apply: `homelab-talos`, `homelab-talos-checks` and
`homelab-talos-light` exist with `minRunners=0` and no `maxRunners`. Fresh guarded
post-deployment plan is empty. CI_EXECUTOR remains unset, preserving hosted
routine execution pending acceptance. No Actions budget changes were made.

## Acceptance status

Runtime scenarios are recorded below only after observation. Deployment and local
contracts do not prove mixed-size GitHub execution, full application compatibility,
GitHub queue expiry, recovery or global routing completion. Unobserved OpenSpec
tasks remain unchecked.

### Live contention and operational commands

- Combined CPU/RAM/scratch exhaustion: PASS, fixture `ba7f9342c22b`.
- CPU exhaustion: PASS, fixture `09862fadd6aa`.
- Each observed StrictFIFO head blocking, pending cancellation, admission after
  successful completion and complete fixture Pod/Workload cleanup.
- During CPU contention, authenticated lifecycle Status returned Off with two
  pending workloads. Stop acknowledged revision 58; Pi-hole TCP and UDP DNS
  queries succeeded. This proves operator reachability during queued work; it
  does not replace AI-running contention or outage tests.

### First GitHub check run

Draft PR #80 contains the implementation. Initial hosted application-plan failed
because workflow-only image edits selected the application root and required a
separate reviewed image build. The correction excludes workflow files and the
runner prerequisite action from infrastructure selection, retains deployment
helper/shared-module consumer selection, and adds coverage for every workflow.
The corrected selector returns an empty general infrastructure matrix for this
PR; the dedicated guarded CI-root workflow still handles admission configuration.

- Memory exhaustion: PASS, fixture `e5bded09c172`.
- Ephemeral-storage exhaustion: PASS, fixture `1a5c397b2934`.
- Both observed FIFO, cancellation, successful-completion release and complete
  Pod/Workload cleanup. Fixture termination grace is now one second because the
  disposable sleepers hold no durable data; reservation cleanup is still observed.
- Corrected affected-state coverage: 24 tests pass, including every workflow file.
- A subsequent hosted config-validation attempt failed on an upstream HTTP 500
  fetching the signed bpg/proxmox provider checksum. Signature checks were retained.

### Controlled Kueue outage

With compute quiesced, scaled the Kueue controller from its observed one replica
to zero and waited for Pod deletion. Status returned AI Off and queue unavailable;
Stop acknowledged revision 59. Pi-hole UDP/TCP DNS succeeded. A server-side compute
Pod creation dry run failed calling the unavailable admission webhook. Restored
exactly one controller replica in `finally` and observed rollout success. No
compute fixture was created and AI remained Off. Controller restart during an
active reservation and node restart remain separate acceptance requirements.

### First mixed-size ARC observation

`mixed-runners-20260915.json` captures simultaneous Running checks (2 CPU/4 GiB/
4 GiB scratch) and Docker (4 CPU/16 GiB/30 GiB scratch) Pods, plus correctly gated
followers. Two Docker runners subsequently ran together, filling the shared
60-GiB scratch quota and leaving smaller followers gated under StrictFIFO.

The first light/checks probes on `a339017` failed because they assumed
`/sys/fs/cgroup/cpu.max` represented the container. Privileged containerd Pods
expose the hierarchy root; the corrected probe resolves `/proc/self/cgroup` and
reads the process's own limit files. Direct inspection of a running Docker
runner observed container `cpu.max=200000 100000`, memory 8589934592 bytes, and
parent Pod `cpu.max=400000 100000`, memory 17179869184 bytes. The failed probes
are preserved and are not claimed as successful job-sized acceptance.

### Cancellation and active controller restarts

GitHub run `34982398521` was cancelled; its assigned runner
`homelab-talos-mgpqp-runner-6gfqs` and matching Kueue Workload were subsequently
absent. Superseded queued proof runs were cancelled to avoid duplicate work.

Restarted Kueue and then ARC through their existing Deployments while five
workloads were reserved and 23 were waiting. Both rollouts succeeded and all
five still-live workload reservations remained admitted after each restart.
No workload finalizers were removed. Node restart remains unobserved in this
migration revision.

The hosted contract check exposed the OpenTofu action wrapper's inability to
forward the console expression on stdin. Console-based contracts now disable
that wrapper and have a 30-second subprocess timeout. The prerequisite action
now installs only missing requested packages; detection and merge helpers no
longer request unrelated networking or build packages.
