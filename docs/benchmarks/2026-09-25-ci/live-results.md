# Live rollout and benchmark results

The implementation and follow-up fixes are merged in [PR 224](https://github.com/TusharSariyaOrg/aws-account-infra/pull/224), [PR 225](https://github.com/TusharSariyaOrg/aws-account-infra/pull/225), and [PR 226](https://github.com/TusharSariyaOrg/aws-account-infra/pull/226). Required gates passed. Current deployed controller/pool sources match main `7f9c9b8b0c40d876e21444f51b868d7e1f3eacd2`.

The existing hosted [management rollout, attempt 2](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/36099609521/attempts/2) applied management and Nexus cache saved plans; both subsequent plans were empty. The coordinator was installed at 05:52:52 UTC on September 25, 2026. Rollback source/configuration remains on the always-on laptop. See [sanitized rollout receipts](rollout-live.json). Thin hosted selection/gates and independent bootstrap/recovery remain; ordinary selected tests and builds execute on Proxmox.

## Actual capacity and parallel placement

| Resource | Before, both workers | First verified live quota after | Change |
|---|---:|---:|---:|
| CPU | 62.5 cores | 70.5 cores | +12.8% |
| Memory | 168 GiB | 202.12 GiB | +20.3% |
| Scratch | 480 GiB | 528.47 GiB | Variable measured capacity |

Primary had 32.65 CPU, 92.65 GiB memory and 91 Pod slots; secondary had 37.85 CPU, 109.47 GiB and 107 Pod slots. These are time-specific quotas after deducting service commitments, not guaranteed free capacity or a fixed concurrent job count. See [capacity observations](capacity-live.json). Running jobs retain their resource reservations even when instantaneous CPU usage is low. ARC still has zero minimum runners and no maximum on all five scale sets.

Before, StrictFIFO prevented a later small job from being admitted during a 26.8-second observation window while a larger older job could not fit. After, BestEffortFIFO admitted the small job while the older job remained queued, and both the existing blocker and small job were observed Running. Separate live tests passed for CPU, memory and scratch exhaustion, fitting-job bypass, queued cancellation and cleanup. The CPU test also checked normal completion released reservations. All test Pods and Workloads were removed. See [timestamped queue assertions](queue-live.json).

The test deliberately cancelled the older request in the before case, so the resulting 70.9 versus 35.7 seconds to small-job admission is **not an unbiased admission-latency speedup**. The demonstrated improvement is packing a fitting job around a larger waiting job. Earlier low concurrency also involved storage-readiness rejection and control-plane incidents, documented in the [original record](README.md).

## Matched real CI: mixed results

The same source revision (`98f78767eeaf66d231405db64cf631f342d895e4`) and same three Proxmox validation jobs ran in [run 36098874952](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/36098874952), attempts 1-3. Both workers were awake. One sample per condition is insufficient to estimate typical performance; unrelated contracts briefly overlapped the before sample.

| Condition | Workflow elapsed | Total allocated runner time | Proxmox job queue times |
|---|---:|---:|---|
| Before live rollout | 102 s | 102 s | 32 / 34 / 35 s |
| After, first new-image pulls | 136 s | 97 s | 64 / 64 / 64 s |
| After, image already present | 118 s | 97 s | 47 / 48 / 53 s |

Warm elapsed time worsened 15.7%, while runner time fell 4.9%. The first after sample included verified 15-16-second image pulls. These jobs do not exercise the new raw dependency cache. Polling/registration delay remains significant, and **no end-to-end speedup is established**. Raw reports: [before](validation-before.json), [first pull](validation-after-first-pull.json), [warm image](validation-after-warm.json).

## Actual Nexus dependency-cache cold/warm pair

Only the applications-plan job was rerun from the same source (`06beb58df5cc0d9febd8f3e70d33f6b3f8427070`) in [run 36097268153](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/36097268153), attempts 2 and 3. Previously successful jobs carried forward by GitHub are excluded from each attempt's runner totals.

| Measurement | Cold raw cache | Warm raw cache |
|---|---:|---:|
| Applications-plan execution | 69 s | 56 s |
| Job queue time | 69 s | 45 s |
| Provider restore | Miss, 0.072 s | Hit, 0.722 s / 22,330,993 bytes |
| Python restore | Miss, 0.064 s | Hit, 0.175 s / 1,817,946 bytes |
| Provider export | 2.271 s | 2.218 s |
| Python export | 0.329 s | 0.542 s |

Execution improved 18.8% in this single isolated pair, including real Nexus transfers. Queue-time differences are not attributed to caching. Warm Python export grew to 3,633,703 bytes. Reports: [cold](provider-live-cold.json), [warm](provider-live-warm.json). [Nexus transfer receipts](nexus-live-metrics.json) retain each hit/miss, byte count and operation duration. Earlier local provider timings excluded HTTP and should not be substituted for these live measurements.

## Acceptance limits

CPU, memory and scratch bypass/cancellation tests are live observations. Pod-slot exhaustion, stale-observation handling, service commitment changes and restart-during-restoration have automated coverage, but their full failure scenarios have not all been induced live. Secondary overflow under a controlled live load remains unmeasured. No claim of complete live acceptance follows from the successful rollout.

The benchmark source still used the Tailscale action’s default GitHub binary cache. A follow-up explicitly sets `use-cache: false` on all 13 invocations, as supported by the [pinned action metadata](https://github.com/tailscale/github-action/blob/306e68a486fd2350f2bfc3b19fcd143891a4a2d8/action.yml#L49). This closes the remaining Nexus-only policy gap; these measurements do not predict its download-time effect.

## Physical shutdown/wake observation

After the benchmark maintenance hold was released, both workers entered the normal five-minute idle countdown. Primary began graceful draining. A scheduled `apps-db-backup` Pod then arrived, causing primary restoration and preventing physical power-off. This demonstrates cancellation of shutdown on new demand, but is **not a completed cold-start measurement**. The backup was not cancelled to manufacture an idle result.
