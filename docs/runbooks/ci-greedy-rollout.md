# Selective CI, Nexus archives and measured worker capacity

Baseline: `0bf4e8f`. Implementation is split into three stages: selective CI and
caching, dynamic admission, and startup acceleration. Existing hardware, physical
shutdown, the configured 300-second idle window, ARC `minRunners: 0`, no ARC maximum,
equal Kueue priority, disabled preemption, environment approvals and storage
identities remain in place.

## Stage 1: selection and caching

PR routine validation shares the hosted `tofu-plan/detect` job. The same selector
runs main-push/manual validation through `ci-validation`. `homelab-config-tests`
runs its children (workflow contracts, ShellCheck/Bats, runner catalog, Proxmox,
Talos) as guarded steps of one `offline` checks pod; each step records a marker and
a final step fails when a selected child did not run, so a silently skipped step
cannot pass `plan-gate`. `homelab-apps-tests` runs lifecycle, PostgreSQL units and
charts the same way in its `charts` checks pod; documents runs on a checks pod with
the subreaper tests under `setpriv --no-new-privs`, and only the PostgreSQL image
build and integration run keep a Docker pod. Editing a suite's own workflow file
selects all of its children. Checkov/TFLint scan affected Terraform directories and local-module consumers
in one runner per tool, amortizing installation across shared changes. PRs compare merge bases; pushes compare before/after;
renames include both paths. Selection errors fail the required `plan-gate`.
The `apply-gate` retains the deployment/acceptance requirements. Selected failures,
cancellations and unexpected skips cannot pass `plan-gate`. Pure validation cancels
superseded runs; mutation ordering and stable publication stay serialized.

Calendar tests select independently. Court-booker tests run natively on the checks
runner; the content-addressed ARM helper is used for packaging only. Calendar infrastructure still owns calendar
packaging. SDK candidate generation, smoke testing and publishing share one job
per target; stable SDK publication retains its existing approval workflow.

Nexus `raw-dependencies` shares the existing bounded default blob store. The
existing cache-only writer gains raw archive privileges; release credentials are
not used. Archives contain only dedicated provider, TFLint, Go or public Python
cache directories under `RUNNER_TEMP`. Keys include format, OS, architecture,
toolchain, dependency hashes, branch and job scope. Job scope is the job id plus an
optional input, not the caller workflow name, so a reusable job keeps one identity
whether `ci-validation` (main) or `tofu-plan` (PRs) calls it; job ids reused across
workflow files pass an explicit scope (`test_ci_optimization` rejects collisions).
Python keys hash `uv.lock`, `pyproject.toml` and `config/ci-python-pins.txt` (every
`--with pkg==ver` pin in workflows and actions) rather than all workflow text.
A branch miss falls back to main's entry for the same identity, read-only: saves
only ever write the current branch's key, so PR writers never populate main. Any
restore hit records `HOMELAB_DEPENDENCY_CACHE_HIT_<KIND>` and the job-end save then
reports `unchanged` without packing or uploading. No state, backend initialization,
plans, checkout trees or credentials are included. Provider lockfiles remain
checked. Cold/missing/unavailable entries rebuild; denied exports are nonfatal;
invalid checksums, unsafe archive members and escaping symlinks fail validation.
Exports stream to disk with 512-MiB compressed/2-GiB expanded limits. Oversized
exports are skipped. Receipts report result, bytes, elapsed time and `fallback`.

PostgreSQL and inference builds use the existing branch/platform BuildKit cache
(imports the branch ref then main's, exports the branch ref only), including
PostgreSQL integration builds. Provenance, SBOMs and immutable published
references are preserved. The runner Dockerfile adds Bats, verified actionlint
1.7.7 and verified gitleaks 8.21.2. The runner image was built, verified and privately published by the existing
workflow; its receipt is in `docs/benchmarks/2026-09-25-ci/runner-image.json`.
The ARC values now pin that verified digest. Management rollout remains required.
Routine image builds use Proxmox; manual dispatch remains hosted for bootstrap.
The final auto-merge API call now runs on the light ARC runner, by the owner's
decision to remove routine hosted-runner dependence; the shared deployment lock is
held until that allocation completes.
Verified installation fallback supports the image transition and recovery.

## Stage 2: dynamic admission

The coordinator calculates each retained worker's effective CPU, memory and Pod
quota from allocatable resources minus non-Kueue commitments. It includes desired
controller replicas saved during sleep, init peaks, restartable sidecars, Pod
overhead, rollouts and live Pods. Pending, unbound compute does not reduce service
capacity. Bound compute without a live reservation remains accounted until it
terminates. Kueue continues accounting for reserved compute even when its CPU is
momentarily idle.

Scratch uses fresh nodefs/imagefs availability and allocatable storage, outstanding
service growth, and measured reserved compute use. It never sums shared filesystem
free space. Kubernetes reservations/eviction deductions remain in allocatable;
there is no additional blanket platform reserve. The retained data-volume identity
and storage preflights remain separate safeguards.

`homelab-compute` uses BestEffortFIFO. All four resources, including Pods, share
worker flavors. Primary is preferred before eligible secondary capacity. A large
job can wait longer while smaller jobs fit. Unreserved work in registered local
queues can wake a worker. Desktop/GPU queues remain outside this power domain.
Sleeping workers retain their last measured potential quota for placement; new
admission requires fresh readiness, storage and capacity checks. Stale/incomplete
observations close new admission. Shrinking capacity does not evict running work.

The coordinator owns only runtime `nominalQuota` fields. Helm owns policy, registered
flavors and admission configuration. Helm's lookup preserves current quotas through
upgrades; a new installation starts at zero. The coordinator rechecks reserved
work against fresh capacity before marking its AdmissionCheck ready. Its RBAC is
restricted to the named ClusterQueue for quota updates.

Application preflight accepts the dynamic queue or the exact reviewed rollback
quotas on every flavor, while still requiring idle work and retained storage. This
allows the PR application apply before the main-only queue upgrade and also makes
the documented rollback usable. It does not cap dynamic quotas at rollback values.

Roll out using the existing hosted `homelab-ci-admission` management plan and saved
plan apply, retaining the `prod` environment and existing idle-runner guards. Deploy
observation/patch RBAC before starting the new coordinator. Install the coordinator
package, regenerate its private configuration with `platform/automatic-power/render-config.py`,
and restart the service (configuration changes already require a restart). Review
per-host `*-capacity.json` and `observations.json` before wake-only acceptance and
normal scheduling. Do not bypass existing automatic-shutdown commissioning gates.

For rollback, restore `pool-values.yaml` from the adjacent
`pool-rollback-values.yaml`, regenerate/restart the coordinator, and use the same
hosted management plan/apply workflow. This restores fixed budgets and StrictFIFO.
Already admitted work is not preempted. No state keys, disks or persistent volumes
need replacement.

## Stage 3: startup and measurement

Inventories use at most four concurrent reads. Missing lists, pagination continuations
or a snapshot taking over 30 seconds fail closed. Wake/restoration polling is five
seconds; idle polling remains fifteen seconds. Restoration starts storage first,
then independent database/cache, Argo and monitoring chains before observing their
readiness. All UID/CAS checks, saved replica counts, storage identities and graceful
shutdown order remain enforced. Interrupted transitions still require the existing
explicit resume procedure; partial restoration is not admission-ready.

Per-host `*-startup.json` records first observations of demand, power-on request,
Proxmox, Talos, platform restoration, Nexus, Kueue admission and ARC registration.
Container start and Pod readiness distinguish runtime/image startup from ARC
registration. First-observation timestamps have polling uncertainty; they are not
claimed as precise hardware event timestamps. Pinned images remain on worker disks.
No snapshots, suspend/resume, warm runners or predictive wake are introduced.

Capture matched completed runs separately:

```sh
python3 scripts/ci-run-report.py RUN_ID --cache-state cold --output cold-run.json \
  --startup /private/evidence/primary-startup.json
python3 scripts/ci-run-report.py RUN_ID --cache-state warm --output warm-run.json \
  --startup /private/evidence/primary-startup.json
```

Compare the same source revision and job set. Report queue time, execution time,
startup phases, total elapsed time and runner-seconds. Use ARC/kubelet event logs
alongside the timestamps to attribute image-pull versus registration delay. The
live `kueue-acceptance.py` proof now sizes contention from observed quotas and checks
that smaller work bypasses larger waiting work on the primary worker. Cancellation
and completion must release reservations without disrupting other running jobs.

## Verification status

Local verification covers complete Git diffs (including 1,102 changed paths),
application/dependency selection, failed/cancelled/skipped gates, archive integrity
and transport failures, ARM helper reuse, effective resource accounting, stale
measurements, unreserved wake/secondary overflow, deletion accounting, bounded
inventory concurrency, partial restoration and restart behavior. Existing controller,
cache, lifecycle, PostgreSQL, Talos and infrastructure contract suites were also run.
Workflow lint, CEL policy cases, OpenTofu validation and static pre-push scanners are
part of the verification record in the PR. Court-booker ARM execution passed locally.

**Live acceptance is incomplete:** hosted management plan/apply and deployment of the pinned runner image
remain subject to the existing deployment controls. Nexus cold/warm
runs, full shutdown/wake timing, real mixed-job overlap, reduced-capacity admission,
and all physical-worker acceptance scenarios must be observed after rollout.
No startup savings or live cache hit rate is claimed by this implementation.
