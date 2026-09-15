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

### Lightweight workflow results and expiry monitor

On `4c64635`, actual ARC catalog validation, Gitleaks, shell checks, SDK spec lint
and backup contracts passed at the declared lightweight size. The identity check
failed because the OpenTofu wrapper invokes `node` from PATH, unlike the runner's
embedded action runtime. All CLI setup steps now use native OpenTofu; none consume
wrapper outputs. This avoids installing an otherwise unnecessary Node dependency.

The independent expiry observer and dispatch-only fixture are implemented with
unit tests for premature cancellation, runner acquisition, reason-review gating
and UID-preconditioned cleanup. A live disposable Pod also verified the raw DELETE
UID precondition path. The 24-hour observation has NOT started and remains unchecked
until other proofs are quiesced. Its 26-hour Pod deadline bounds a lost observer.

The corrected lightweight cgroup probe passed on ARC. SDK Python generation also
passed in the Docker configuration. ARM packaging then exposed a selector bug:
its steps still tested global CI_EXECUTOR while the PR label selected Talos.
QEMU and packaging now follow the actual runner architecture, covering both
label-driven proofs and later global routing. Odysseus upstream browser-source
tests explicitly install Node 22; both image-publication jobs explicitly request
the GitHub CLI used to verify private package visibility. Resource budgets were
not increased in response to these prerequisite failures.

### Expanded actual ARC compatibility

On `dcd1064`, the full ARC acceptance workflow `34985213037` passed: both
1-CPU/2-GiB and 2-CPU/4-GiB cgroup probes, checkout, privileged disposable fixture,
ARM Linux tests and private cluster networking. Actual ARC runs also passed
Checkov (`34985212903`), recovery identity/contracts (`34985212918`), Gitleaks
(`34985212849`), Ansible (`34985212846`), application contracts (`34985213183`),
config validation (`34985212953`), TFLint (`34985212963`), Trivy (`34985212788`)
and catalog validation (`34985212894`). These retain their exact source revision.

LocalStack run `34985212825` exposed an initialization race: S3 bootstrap completed
at 15:45:56 UTC, while smoke queried the not-yet-created SQS queue at 15:45:58 UTC.
Compose health now requires successful ready-hook completion, including the named
bootstrap script. The isolated Mac verification passed smoke and three integration
tests; three tests requiring private external booking credentials/SDK inputs were
skipped. The disposable local Compose project was removed. ARC re-verification is
still required for this correction.

### Actual queued AI Start/Stop with CI active

Start revision 59 was acknowledged as revision 60 with real CI running. AI's Pod
`ai-runtime-b9c9c8b58-9dqlt` remained SchedulingGated, requested 35.75 CPU/77 GiB,
reported no reservation and idle_seconds=0, and appeared at queue position 17 in
a later sample. Stop revision 60 was acknowledged and Pod deletion was observed.
This proves queued Start/Stop without idle accrual; full AI-running contention
and admission after CI completion remain separate unchecked tasks.

### Real ARM packaging and candidate upload

Run `34993774678` on source `b59af9a` completed successfully on ARC. The ARM Linux
fixture reported 32 tests passed. The authenticated packaging step uploaded
`s3://lambda-releases-992382747916-us-east-1/candidate/court-booker/d63523379925f29e921fbe05302bb26b5f7ad21a.zip`
at 16:36:23 UTC. The artifact key is the PR merge revision used by that workflow.
This is an actual candidate upload, not only a local/emulated test. Lambda was
not retargeted by this proof.

The expiry observer now cancels its own unfinished GitHub fixture before releasing
the blocker on an interrupted observation, tracks replacement runner Pod UIDs in
cleanup checks, and holds a Mac idle-sleep assertion for the observer lifetime.
Five focused observer tests pass. The full-duration observation is still pending.

### Cancellation-aware result gates

Normal cancellation of superseded runs `34992935278` and `34992935066` left their
`always()` publish/plan gate jobs queued after other jobs were cancelled. Repeated
GitHub API observations reproduced the symptom; force cancellation completed both
runs through GitHub without removing Kubernetes finalizers. GitHub documents that
`always()` job conditions remain true during cancellation:
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-cancellation

Job-level result, acceptance and comment gates now use `!cancelled()` so they can
still report ordinary dependency failures but do not keep a cancelled workflow
queued. Step-level credential and artifact cleanup conditions are retained.
Actionlint and 24 affected-state selection tests pass. A live normal-cancellation
recheck of the revised workflow remains required; local syntax checks do not
simulate GitHub's cancellation engine.

### LocalStack correction verified on ARC

Run `34993774685` on `b59af9a` passed 35 unit tests, sandbox readiness, the actual
LocalStack smoke test, and three integration tests. Three external credential/SDK
fixture tests remained skipped. The integration phase completed at 16:52:28 UTC.

### Shared temporary Docker fixtures

The actual Ollama smoke controller exited while its `/tmp` bind source existed
only in the runner container. A bounded read-only bind fixture reproduced the
failure in one second: Docker reported that the `/tmp` source path did not exist.
The identical fixture passed with TMPDIR under `/home/runner/_work/_temp`.
Docker-enabled setup now exports RUNNER_TEMP as TMPDIR for subsequent steps,
keeping bind-mounted temporary files in the existing shared disposable volume.
The ARC acceptance workflow includes this actual mount-read regression check.
No host mounts or resource increases were introduced. The complete image workflow
must still pass with this correction before its receipt can be selected.

### Revised gate cancellation passed on GitHub

On source `40808a6`, run `34998704455` was normally cancelled while `detect` was
queued behind AI. GitHub completed `detect`, `publish-stable`, `enable-auto-merge`
and `publish-gate` as cancelled at 17:02:40 UTC; no result gate remained queued
and no force cancellation was used. This reproduces the original stuck-gate
scenario against the revised condition. The run was then rerun for its normal
current-revision check result.

On `40808a6`, ARC compatibility (including shared temporary bind mounts), ARM
packaging/upload, ECR build/publication, LocalStack, all scanners, configuration
and recovery contracts passed. Storage acceptance identified a missing explicit
Helm prerequisite, now added. The hosted admission contract still asserted the
superseded `always()` condition; the corrected suite passes all 24 tests and 15
CEL cases locally. SDK generation/smoke progressed, but Python candidate publishing
hit a Docker registry connection failure and was rerun independently.

The first AI observation captured admission after CI cleanup and later verified
idle shutdown, but an observation gap prevents crediting full On-state contention.
Its raw record is retained privately and the complete contention task stays open.

### Actual AI-first blocking and Stop release

The second bounded observation reached AI On at revision 64 with verified Ollama
and Odysseus identities. Rerunning the real SDK candidate workflow created an ARC
runner behind AI. For over one minute AI held 35.75 CPU/77 GiB while the runner
remained gated and CI held no reservation. The observer issued Stop revision 64;
revision 65 reached Off, the AI workload disappeared and the SDK runner entered
initialization. No observation gap was recorded in this successful interval.

### Image fixture DNS isolation

Both image smoke callbacks failed after publishing. A direct Docker-network probe
on ARC showed inherited `ndots:5` resolving `ai-lifecycle.homelab-platform.svc` to
the real Kubernetes service `10.110.7.252`, while the disposable controller was
`172.18.0.2`. The identical lookup with `--dns-option ndots:0` returned the fixture
address. Smoke containers now use this explicit option; production endpoints,
authentication and resource budgets are unchanged. The bounded probe network and
containers were removed. Full image workflow re-verification remains required.

### CI-first On-state proof and complete SDK run

The third bounded observation started while the real Python SDK candidate job held
CI capacity. AI was first gated with no idle accrual, then admitted after publication
finished. It reached On for a full minute while the later SDK comment runner waited.
Stop moved revision 66 to 67; Off and an empty Kueue workload list were subsequently
observed. Both AI-first and CI-first complete observations are now retained privately.
SDK run `34998704606` completed successfully after retry: both generated SDKs,
both smoke tests, both candidate publications and the final comment passed on ARC.
