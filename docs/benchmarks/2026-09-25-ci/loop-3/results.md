# CI optimization loop, iteration 3

Branch `perf/ci-loop-3`, PR #231 (base `perf/ci-loop-2`). Raw per-job data: `iteration3-cold.json`. Same measurement method as loop-1.

## Changes measured here

- Full fan-out consolidated from 17 to 11 pods: one `homelab-config-tests / offline` pod (workflow, proxmox, talos, shell, runner-catalog), `lifecycle` folded into `charts`, `documents` moved from docker-small to checks, one `offline-validation / offline` pod for kubernetes and main-platform validation.
- Job-level `tofu-apply` lock; shared selector for ecr-push and sdk-publish-stable; readiness diagnostic; cache-transport backoff.

## Cold run (first push, `1d407b7`; branch caches cold because every job id changed)

| run | fan-out end | ARC pods | ARC exec sum | ARC queue sum | note |
|---|---|---|---|---|---|
| tofu-plan 36138722399 | +405 (postgres) | 10 + gate | 698 | 1000 | `plan-gate` never started (see below); `talos-plan` hosted and refused for billing |
| lambda-package 36138722250 | +819 | 5 | 704 | 371 | `package` 522s: ARM helper rebuilt again (BuildKit cache identity changed with the loop-2 scope change, first run on this branch) |
| tofu-apply 36138722505 | +430 | 6 + gate | 535 | 804 | `acceptance (pvc)` failed after 116s in `homelab-storage-validate.py` (private output); `apply-gate` never started |

Per job, loop-2 warm -> loop-3 cold: config suite 18+21+46+27+32 = 144s across 5 pods -> 88s in 1 pod; offline-validation 26+44 = 70s across 2 pods -> 38s in 1 pod; documents 33s on docker-small (queue 228) -> 36s on checks (queue 73); charts 44 -> 63 (absorbed lifecycle 30s); identity 97 -> 147 (cold provider cache on the new branch; the fallback to main cannot help until main carries the new cache identities).

ARC queue sum for the tofu-plan fan-out: 1593 (loop-2 warm, 17 pods) -> 1000 (loop-3 cold, 10 pods). Pod starts avoided: 6 per full fan-out, about 7 minutes of runner-seconds.

## Incident during the cold run

After `acceptance (pvc)` failed at 13:11 UTC, no new `homelab-talos-light` pod was admitted: both gates stayed queued for over 30 minutes while `detect` on the same label had started in 47s minutes earlier. This matches the Kueue admission design in `docs/runbooks/ci-greedy-rollout.md` ("new admission requires fresh readiness, storage and capacity checks; stale or incomplete observations close new admission") and is a cluster-side condition, not a workflow change. Warm re-runs were not possible until the cluster admitted pods again.
