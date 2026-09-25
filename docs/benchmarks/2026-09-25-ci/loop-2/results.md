# CI optimization loop, iteration 2

Branch `perf/ci-loop-2`, PR #230 (base `perf/ci-loop-1`). Raw per-job data: `iteration2-cold.json`, `iteration2-warm.json`. Same measurement method as loop-1.

## Changes measured here

- Mac operator runner routing for cluster-mutating maintenance (`vars.CI_OPERATOR`), macOS branches in composites, runner bootstrap script and runbook. No effect on routine PR timing.
- Dependency cache: read-only fallback to main's key on a branch miss; save skipped after any hit; cache scope no longer includes the workflow name; python cache key hashes `config/ci-python-pins.txt` instead of every workflow file.
- Postgres: unit tests moved to `charts`; integration servers run from the just-built image instead of a second ghcr pull.

## Cold run (first push, `5ddde9d`)

| run | wall | ARC pods | ARC exec sum | ARC queue sum | first pod queue | note |
|---|---|---|---|---|---|---|
| tofu-plan 36134916285 | 1318 | 17 | 1026 | 4122 | 630 (host wake) | `talos-plan` selected by the `talos_tools.py` change and refused by hosted-runner billing, so `plan-gate` failed; suite timings still valid |
| lambda-package 36134915974 | 1532 | 5 | 825 | 1131 | 628 | `package` 514s: BuildKit cache scope changed, so the ARM helper image rebuilt from scratch under QEMU |
| tofu-apply 36134916358 | 1442 | 7 | 536 | 2586 | 631 | `apply-gate` correctly demands the `apply` label because a deploy unit (talos-homelab) is selected |

Not comparable to loop-1: the workers had gone back to sleep (about 10.5 min wake), and because this PR touched `.github/actions/**` it also triggered `ci-runner-image`, `ollama-image`, `odysseus-image` and `postgres-backup-image` builds on the same pool, which pushed queue waits to 250 to 600s.

Per-job execution on the cold run (all first-time cache identities): identity 155, checkov 140, postgres 117 (was 122 to 136 in loop-1 with the python tests still inside), charts 63 (now carries the postgres unit tests), lambda test 120, lambda package 514.

## Warm re-runs (attempt 2 of the same runs, pool otherwise idle apart from the three workflows)

| run | wall | ARC pods | ARC exec sum | ARC queue sum | critical path |
|---|---|---|---|---|---|
| tofu-plan | 423 (gate failed on hosted `talos-plan`; suite fan-out ended at +348) | 17 | 686 | 1593 | documents/postgres on docker-small, queue 185 to 228s |
| lambda-package | 558 | 5 | 348 | 617 | package (queue 58, exec 204) after test |
| tofu-apply | 544 (gate correctly demands the `apply` label) | 7 | 539 | 643 | acceptance (pvc) 215s |

Per-job execution, loop-1 warm -> loop-2 warm: identity 119 -> 97; checkov 108 -> 73; postgres 122 -> 71 (unit tests moved to charts, servers from the built image); charts 44 -> 44 despite absorbing the postgres unit tests; main-platform 53 -> 44; kubernetes-validation 31 -> 26; trivy 73 -> 60; lambda test 73 -> 46; lambda package 204 -> 204.

Reading:

- ARC execution for the tofu-plan fan-out dropped from 849s to 686s (-19%) with the same 17 pods; this is the cache fallback to main and the skipped saves doing their job on a branch whose own caches were cold one run earlier.
- Wall clock did not improve because the two docker-small pods (documents, postgres) queued 185 to 228s: the docker-small scale set was still draining the image builds from the cold run and tofu-apply's storage-foundation pod. Iteration 3 moves `documents` off docker-small, leaving one docker pod per PR.
- `talos-plan` was selected because `scripts/talos_tools.py` is in the talos-homelab unit's watch list. It is routed to hosted until `vars.CI_OPERATOR=mac`, and hosted runners were refused for billing, so `plan-gate` failed. This is the expected state until the operator runner is registered.
