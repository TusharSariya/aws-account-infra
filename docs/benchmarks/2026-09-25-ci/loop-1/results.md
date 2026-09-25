# CI optimization loop, iteration 1

Branch `perf/ci-loop-1`, PR #229, base `e1516dc`. Raw per-job data: `baseline-main.json` (main, 2026-09-25 06:42 to 06:49 UTC, warm workers) and `iteration1-cold.json` (first run after push, workers asleep). Measurements come from the GitHub jobs API: queue is job created to job started, exec is started to completed, wall is run created to last job completed.

## Changes

- lambda-package: court-booker pytest runs natively on `homelab-talos-checks` in a new `test` job; `package` (QEMU arm64 build and upload) depends on it and no longer runs tests.
- homelab-recovery-tests: `backup-contracts` folded into `identity`; `identity` moved to `checks` and restores/saves the OpenTofu provider cache from Nexus.
- checkov: runs pinned `checkov==3.3.19` through `uvx` on `checks` with `--quiet` instead of `docker run` on `docker-small`.
- kubernetes-validation: checksummed kubeconform release tarball instead of `setup-go` plus `go install`.
- tflint, trivy, shell: shallow checkouts; placeholder steps removed.
- Every routine selection, gate, auto-merge and offline validation job routes through `vars.CI_EXECUTOR`, so no routine job uses GitHub-hosted runners; `ubuntu-latest` is the fallback when the variable is unset. Enforced by `scripts/tests/test_ci_executor_routing.py`.

## Per-job execution time (seconds, excludes queue)

| job | baseline (main, warm) | iteration 1 cold | note |
|---|---|---|---|
| lambda-package / package | 441 (Test 248 + Package 147) | 198 | tests moved out; build cache cold on new branch |
| lambda-package / test (new) | n/a | 58 | native pytest, replaces 248s QEMU step |
| checkov / checkov | 138 | 98 | cold uvx install of 96 wheels included |
| homelab-recovery-tests / identity | 158 | 145 | provider cache miss on first branch run |
| homelab-recovery-tests / backup-contracts | 18 | folded | -1 pod |
| kubernetes-validation / offline | 45 | 32 | on ARC checks now |
| main-platform-validation / offline | 12 | 42 | on ARC checks now; cold uv |
| homelab-apps-tests / postgres | 151 | 136 | unchanged job |

## Run level

| run | hosted jobs | ARC pods | ARC exec sum | ARC queue sum | wall |
|---|---|---|---|---|---|
| tofu-plan baseline 36104102485 | 4 | 16 | 843 | 891 | 253 |
| tofu-plan iteration 1 cold 36129893416 | 0 | 17 | 864 | 2655 | 1073 |
| lambda-package baseline 36104585441 | 1 | 3 | 544 | 404 | 722 |
| lambda-package iteration 1 cold 36129892911 | 0 | 5 | 380 | 1150 | 1284 |

The cold iteration 1 wall clock is dominated by a worker wake: `detect` waited 516s before the first pod started, then 28 pods across tofu-plan, tofu-apply (the PR touched `tofu-*.yml`, which selects all four acceptance suites) and lambda-package requested about 54 CPU at once, so Kueue serialized the tail (`kubernetes-validation`, `main-platform-validation` and the acceptance legs waited about 450s). Warm runs follow below.

## Warm run 1 (empty commit `b18337f`, workers awake, branch caches populated by the cold run)

| run | wall | ARC pods | hosted | ARC exec sum | ARC queue sum | first pod queue | critical path |
|---|---|---|---|---|---|---|---|
| tofu-plan baseline | 253 | 14 | 4 | 843 | 891 | 3 (hosted detect) | plan-gate +253 |
| tofu-plan warm 1 (36131959365) | 388 | 17 | 0 | 849 | 1367 | 70 (ARC detect) | plan-gate +388 |
| lambda-package baseline | 721 | 3 | 1 | 544 | 404 | 4 | package +721 |
| lambda-package warm 1 (36131959093) | 527 | 5 | 0 | 418 | 379 | 68 | package +527 |
| tofu-apply baseline | 367 | 5 | 2 | 519 | 429 | 4 | apply-gate +367 |
| tofu-apply warm 1 (36131959393) | 474 | 6 | 0 | 501 | 430 | 70 | apply-gate +474 |

Per-job execution, warm 1 vs baseline: identity 119 vs 158; checkov 108 vs 138; postgres 122 vs 151; kubernetes-validation 31 vs 45; lambda `test` 73 (native) vs the 248s QEMU step; lambda `package` 204 vs 441.

Reading:

- Moving `detect`/`select` and the gates to ARC costs one pod start at each end of every workflow: about 70s before the fan-out begins and about 70s after it ends. That is the whole tofu-plan regression (+135s) and tofu-apply regression (+107s). It is the accepted price of zero routine hosted-runner use. The fan-out itself (first suite start to last suite end) is unchanged at about 230s.
- lambda-package is 194s faster end to end and 126s cheaper in runner time. It could be another ~150s faster if `package` did not wait for `test` (they would run in parallel), at the cost of uploading a candidate zip before its tests pass. Left serialized on purpose.
- identity and checkov are still on the critical path with the postgres job; identity spends about 50s in `tofu test` that no cache can remove, and checkov's `uvx` install shows no cache benefit yet (branch-scoped Nexus cache; see iteration 2 cache work).
## Warm run 2 (re-run of the same runs, attempt 2)

| run | wall | ARC pods | ARC exec sum | ARC queue sum | critical path |
|---|---|---|---|---|---|
| tofu-plan attempt 2 | 361 | 17 | 825 | 1591 | plan-gate +361 |
| lambda-package attempt 2 | 570 | 5 | 372 | 577 | package +570 |
| tofu-apply attempt 2 | invalid | | | | acceptance jobs rejected by a `prod` deployment branch policy that was briefly applied during this run and then reverted; not a CI regression |

Warm medians so far: tofu-plan 375s (baseline 253s), lambda-package 549s (baseline 721s). Queue per pod stayed in the 85 to 120s band on attempt 2 because the three workflows re-ran together and the light pool served `detect` and `workflow` back to back (workflow waited 181s).

- The per-label queue floor is 68 to 86s for every pod even when the pool is idle. That is ARC pod scheduling plus runner registration, and it now bounds everything: 17 pods with 70s of dead time each is about 20 minutes of runner-seconds per PR spent waiting. Consolidating micro-jobs (iteration 2) attacks this directly.
