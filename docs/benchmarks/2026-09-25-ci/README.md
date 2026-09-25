# CI optimization benchmark record - 2026-09-25

PR: https://github.com/TusharSariyaOrg/aws-account-infra/pull/224

These results distinguish matched component measurements, historical context,
and live read-only capacity observations. **They do not establish an end-to-end
CI or physical wake speedup.** Dynamic quotas and BestEffortFIFO were not deployed
when the snapshots were taken. Full post-rollout cold/warm acceptance remains open.

## Matched before/after measurements

Application baseline: `71458e12` (current main after the audited `0bf4e8f`).
After: `f2f6194580523ae0f711e9f392e1b9479a9a8ace`. Court-booker source and dependencies
are identical between these two checkouts; only orchestration differs. Each ARM
execution passed **96 tests, 2 skipped**. Order alternated between variants.

| Measurement | Samples per variant | Before median | After median | Reduction |
|---|---:|---:|---:|---:|
| ARM helper + tests, cold dependency directory | 6 | 9.893 s | 9.076 s | 8.3% |
| ARM helper + tests, warm dependencies | 5 | 5.765 s | 5.358 s | 7.1% |
| OpenTofu init, cold providers vs restored archive | 3 | 2.572 s | 0.654 s | 74.6% |
| Live Kubernetes inventory, sequential vs bounded concurrent | 5 | 5.559 s | 4.859 s | 12.6% |

ARM cold ranges were 9.463-12.253 seconds before and 8.842-9.656 after. Warm ranges
were 5.730-5.948 and 5.268-5.524 seconds. BuildKit layers and helper images were
already present; "cold" here means an empty dependency cache and virtualenv. The
host used native ARM Docker on macOS, **not x64 CI emulation**. Warmup pairs were
excluded from the warm medians. Real packaging/upload was not benchmarked locally.
The helper reuse contract separately verifies one build across test and packaging.

Provider tests used OpenTofu 1.11.5 and the committed bpg/proxmox lockfile on
`darwin_arm64`, with a fresh backend-disabled root each time. Restores include
archive integrity verification and extraction; **Nexus HTTP time is excluded**.
The archive was 10,243,632 bytes from 27,623,976 bytes of dependencies; export cost
0.295 seconds. The median local saving leaves about 1.62 seconds for combined
upload/download before export-plus-restore breaks even in this small fixture.
Larger providers, platform differences and Nexus throughput require live measurement.

Inventory pairs ran on the actual always-on laptop against the actual cluster,
while CI work continued. Before reads 14 resource lists serially; after reads 16
lists with concurrency bounded at four, including complete-snapshot validation.
The sample is noisy: before 4.788-9.427 seconds, after 4.040-6.258 seconds; one
pair was slightly slower after. No total wake-time claim follows from this sample.
A separate 50-ms-per-read controlled fixture is stored in `inventory.json`; it is
an algorithm check, not a measurement of real server startup.

## Live capacity and the observed queue

At 03:00 UTC the live queue still used StrictFIFO and fixed 31.25 CPU / 84 GiB /
240 GiB quotas per worker. Reservations used 30 CPU on both workers, 84 GiB on
primary and 76 GiB on secondary. There were 19 admitted, 25 reserving and 39 pending
workloads. The first pending 2-CPU job needed another 750 millicores on either
worker; later 1-CPU jobs could fit on secondary but waited behind it. Nearby GitHub
observations showed 14 busy runners out of 20 online across workflows.

At 03:02 UTC, the new calculation ran read-only against fresh inventories, kubelet
filesystem statistics and existing restoration journals:

| Worker | Old CPU quota | Measured potential CPU | Old RAM quota | Measured potential RAM |
|---|---:|---:|---:|---:|
| Primary | 31.25 | 32.64 | 84 GiB | 92.64 GiB |
| Secondary | 31.25 | 37.85 | 84 GiB | 109.47 GiB |

Combined CPU potential was 70.49 rather than 62.50 (+12.8%). These are instantaneous
potential quotas, not installed quotas or a guaranteed job count. Primary service
commitments were 5.31 CPU; secondary commitments were 0.10 CPU. Requests of existing
reserved compute remain accounted by Kueue. Storage availability and service
commitments change over time; the coordinator must remeasure before admitting work.
No running workload was terminated and no quota was patched for this benchmark.

## Historical context (unmatched)

Twenty successful runs from September 24-25 were fetched through GitHub's jobs API.
Source revisions and job sets differ; cache/worker power state is unknown. These
numbers are **not a controlled before/after comparison**. Queue time is job
created-to-started; inconsistent negative timestamps and jobs without allocated
runners are excluded. Raw job and step timings, revisions and run URLs are retained
in `historical.json`.

| Workflow | Runs | Median workflow elapsed | Median summed runner-seconds |
|---|---:|---:|---:|
| homelab-apps-tests | 3 | 840 s | 126 s |
| homelab-ci-admission | 1 | 518 s | 342 s |
| homelab-config-tests | 5 | 970 s | 160 s |
| lambda-package | 4 | 975 s | 544 s |
| tofu-plan | 7 | 942 s | 241 s |

The 12 sampled OpenTofu initialize steps took 45-57 seconds. Configuration jobs
waited 658-1211 seconds. This supports separating runner wait, tool execution and
physical startup in follow-up measurements; it does not identify all waiting time
as server boot time.

## Reproduction and remaining work

```sh
python3 scripts/benchmarks/arm-helper.py --before /path/to/main-checkout \
  --after /path/to/pr-checkout --output /tmp/arm-comparison
python3 scripts/benchmarks/providers.py --tofu /path/to/real/tofu-1.11.5 \
  --output /tmp/provider-comparison
python3 scripts/ci-run-report.py RUN_ID --cache-state cold --output cold-run.json
python3 scripts/ci-run-report.py RUN_ID --cache-state warm --output warm-run.json
```

The real uv-cache integrity regression was reproduced in Linux ARM. Generated
virtualenvs live inside `archive-v0` as well as `environments-v2`; interpreter links
must not be archived. The fix excludes those disposable environments, build/source
cache directories and interpreter metadata, while retaining public wheel archives.
A real restored PyYAML wheel was installed offline successfully. Arbitrary external
symlinks and corrupt archives remain fatal. Matrix jobs use distinct cache scopes.

The pinned runner image was published and verified by the existing hosted workflow;
see `runner-image.json`. Routine image builds and inference validation now use
Proxmox. Manual runner-image bootstrap and independent infrastructure management
retain their hosted recovery path. Hosted selector/gate jobs remain thin.

Still required: green final PR gates, merge, hosted management saved-plan apply,
coordinator deployment, real BestEffortFIFO bypass/cancellation proof, matched
Nexus cold/warm cohorts, secondary overflow and resource exhaustion checks, and
complete physical shutdown/wake phase timing. These results must be appended after
observation; no estimated savings should be presented as measured outcomes.

## Recovery discovered during live validation

The installed Kueue 0.19.4 manager entered CrashLoopBackOff while the queue was
under load. Logs ended with `leader election lost`; admission dry-runs failed
because the Kueue validation webhook refused connections. The failed request's
resourceVersion was unchanged, ruling out the suspected compare-and-swap race for
that sample. No retry weakening was implemented.

The [0.19.5 upstream release](https://github.com/kubernetes-sigs/kueue/releases/tag/v0.19.5)
fixes lease renewal sharing a client-side rate limiter with controller requests
and redundant status writes. The current stable 0.19.6 image includes those fixes.
A scoped Helm recovery reused the existing 0.19.4 chart, live values and repository
post-renderers. A structural render comparison proved that **only the manager
container image changed**. Helm `--atomic --wait` succeeded from revision 8 to 9
at 03:28:46 UTC; see `kueue-recovery.json`. The matching image digest is pinned in
`kueue-values.yaml`. ClusterQueue quotas/policy and running compute were unchanged.
The image upgrade alone did **not** stabilize the control plane: follow-up
observations recorded further lease-timeout restarts.

Private release backups are retained on the operator laptop under
`~/.local/share/homelab-ci-recovery/20260925-kueue/`. Broader management rollout still
uses the existing hosted saved-plan workflow. This recovery affects comparisons of
full pipeline behavior: report it separately from selective CI and greedy quotas.

### Runner initialization failure during live validation

One Docker runner's `init-dind-externals` copy process terminated with
`OOMKilled`/137 after 20 seconds at its 128-MiB limit; see
[the sanitized Pod receipt](runner-init-oom.json). The proposed init budget is
512 MiB and 250m CPU. Catalog rendering and 16 catalog/admission contract tests
pass, including unchanged whole-Pod reservations: the subsequent runner plus
Docker sidecar already dominates the init peak. A live retest requires the managed
ARC rollout. No additional concurrent jobs are claimed from this change alone.

During the same validation window the always-on laptop had intermittent API
timeouts and elevated disk I/O pressure (60-second some/full PSI approximately
64%/33%). These observations are a separate scheduling bottleneck; they are not
evidence of exhausted Proxmox worker CPU. No hardware or control-plane resource
changes were made in response to that transient measurement.

### Successful pre-rollout Lambda validation

[Run 36090684623](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/36090684623)
passed on the new workflow with the old live placement configuration. Total elapsed
time was 782 seconds and allocated runner time was 588 seconds; the hosted selector
used 6 seconds, with the remaining 582 runner-seconds on Proxmox. Court-booker
packaging waited 292 seconds and executed for 459 seconds. The two calendar jobs
started one second apart, confirming overlap. See [job timings](lambda-live.json).
Cache state is deliberately unknown/mixed: BuildKit imported existing caches,
while the new raw dependency export was unavailable before repository rollout.
This is an observational success, not a matched end-to-end before/after benchmark.

### Control-plane recovery and measurement confounders

The control-plane VM subsequently showed sustained memory and I/O pressure; its
API server used approximately 2.6 GB RSS in a 4.8-GB VM. API/VIP access and kubelet/CRI
health checks timed out. Restarting the identified API-server process through Talos
reduced observed VM used memory from 3,897 to 2,075 MiB and increased available
memory from 643 to 2,464 MiB. API readiness recovered. See
[the recovery receipt](control-plane-recovery.json). This is recovery evidence,
not a software before/after benchmark or proof that memory growth cannot recur.

Kueue's chart default debug verbosity emitted at least 2 MB in a 30-second sample.
The PR sets `logLevel: info`. An initial numeric `0` attempt was rejected by the
binary and automatically rolled back by Helm (revision 10 failed, revision 11
restored revision 9). The corrected informational setting deployed successfully as Helm revision 12;
the replacement manager was ready with zero restarts at first observation. See
[the logging recovery receipt](kueue-logging-recovery.json). Long-term stability
and resource pressure still require observation.

The closest historical Lambda run on main,
[36086620084](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/36086620084),
executed its single package job in 454 seconds after 91 seconds of queue time.
The observed PR package job took 459 seconds (+1.1%), and all PR jobs used 588
runner-seconds versus 454 (+29.5%). Splitting calendar jobs adds independent setup
and cache-export work; iRacing testing took 35 seconds and its export step took
12 seconds in the PR sample. Queueing also worsened during the incident. These
uncontrolled live samples do not demonstrate an end-to-end improvement. Savings
from selecting fewer jobs and from dynamic admission require separate matched
workload cohorts after rollout.

Across the interleaved native-ARM test measurements, all six cold-dependency
pairs and all five post-warmup warm pairs were faster after the change. The table
reports percentage changes in cohort medians; median paired percentage changes
were 6.9% cold and 7.1% warm. The small sample and native-ARM platform still limit
generalization to emulated CI and full pipeline execution.
