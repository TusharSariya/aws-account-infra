# Manual Kubernetes validation

Run this suite **on the Ubuntu laptop**, outside Kubernetes. It tests the isolated
`laptop-wifi-PROTOTYPE` cluster using the existing controllers. It does not install
controllers, resume paused hosts, change quotas, power off physical hosts, or
transfer production ownership. Python 3.11+ and the pilot's `kubectl` are required.
No Python packages are needed at runtime.

```sh
python3 validation/kubernetes/install-kube-burner.py
python3 validation/kubernetes/suite.py list
python3 validation/kubernetes/suite.py preflight
python3 validation/kubernetes/suite.py run --scenarios smoke
python3 validation/kubernetes/suite.py run --scenarios queueing,impossible,placement-reuse,services
python3 validation/kubernetes/suite.py run --scenarios load-bursts,load-sustained
python3 validation/kubernetes/suite.py run --scenarios all
```

Every live run performs its own smoke check before other scenarios. `all` requests
all implemented scenarios; future capabilities remain explicitly deferred. A
requested deferred ID becomes **blocked**, never passed. Missing initial state
(e.g. zero workers, two unpaused Ready workers, a disposable StorageClass) also
blocks the corresponding scenario. Read the report even when the command fails.

The supplied profile reflects the pilot documented on
[`feat/homelab-power-adapter`](https://github.com/TusharSariyaOrg/aws-account-infra/tree/cd48f53/prototypes/one-slot-autoscaler).
The two-worker production manifests in this checkout are **not** the pilot target.
Copy `profiles/pilot.json` and pass `--profile /path/to/profile.json` for local
paths or reviewed target changes. Never point the pilot profile at production.
`kube_system_uid` pins the verified pilot UID; an uninitialized profile may leave it null, but every run also captures
that UID and checks it before mutations and cleanup. The profile is saved with
the report so cleanup cannot silently switch targets.

## Coverage and prerequisites

| Scenario | Assertions | Prerequisite / proof reference |
|---|---|---|
| `smoke` | Kueue admission, DNS lookup, completion, selector placement | Active pilot queue and primary unpaused |
| `queueing` | Quota reservations fill; extra Job stays suspended; cancellation removes owned Pods/Workloads; completion releases reservations | No foreign queue demand; quota-fill count fits max_jobs; [#107](https://github.com/TusharSariyaOrg/aws-account-infra/issues/107) |
| `impossible` | Over-quota and unsupported-selector Jobs stay suspended without provider-target or node expansion | Stable controller state; [#107](https://github.com/TusharSariyaOrg/aws-account-infra/issues/107) |
| `placement-reuse` | Fitting work reuses Ready worker without expansion | Existing schedulable primary; [#109](https://github.com/TusharSariyaOrg/aws-account-infra/issues/109) |
| `placement-packing` | Small Jobs pack on busy eligible secondary | Two unpaused Ready workers; [#109](https://github.com/TusharSariyaOrg/aws-account-infra/issues/109) |
| `placement-overflow` | 1200m holder plus 1200m overflow causes second-worker expansion | Only secondary initially Ready, both slots unpaused; [#109](https://github.com/TusharSariyaOrg/aws-account-infra/issues/109) |
| `scale-from-zero` | Queued demand executes on newly Ready worker | Zero pilot workers at scenario entry; no forced retirement; [#107](https://github.com/TusharSariyaOrg/aws-account-infra/issues/107) |
| `idle-recreation` | Existing controller's idle window, retirement, returning demand, fresh node UID and hardware UUID | Two Ready workers, empty eligible primary, installed lifecycle/observer with matching idle setting; [#111](https://github.com/TusharSariyaOrg/aws-account-infra/issues/111) |
| `retirement-cancellation` | Returning demand clears timer, preserves and reopens original node | Same lifecycle prerequisites; [#111](https://github.com/TusharSariyaOrg/aws-account-infra/issues/111) |
| `consolidation` | PDB refusal without replacement; persistent-policy blocker; eligible Deployment movement | Two unpaused workers, existing empty `prototype-consolidation` namespace, existing pilot controller; [#110](https://github.com/TusharSariyaOrg/aws-account-infra/issues/110) |
| `services` | DNS, Service and Pod-IP connectivity, readiness endpoint publication/withdrawal, allowed/denied ingress | NetworkPolicy enforcement in pilot CNI |
| `storage` | Fresh marker write/read on same PVC across Pod replacement, selector and PV claim identity, disposable PV cleanup | Explicit disposable **Delete** StorageClass and eligible storage worker; never use `retained-marker` |
| `load-bursts` | 4, 8, 16 short Jobs complete, excess demand queues | Pinned kube-burner and live profile quota |
| `load-sustained` | Four bounded CPU/memory/scratch Jobs run for ten minutes | Same load prerequisites |

The initial queue budget is 3 CPU, 4 GiB memory and 20 GiB scratch. Burst Jobs each
request and limit 250m CPU, 128 MiB memory and 64 MiB ephemeral storage. Their probe
holds one quarter of the memory allowance in a memory-backed volume, fills scratch with a
1-MiB margin (capped at half the memory budget so dirty page cache and tmpfs
leave at least a quarter of memory for the process), and runs a CPU loop under its CPU limit. Defaults are 30 seconds per
burst Job and 600 seconds for each sustained Job. No saturation, exhaustion or
failure injection is included. Volume, concurrency and durations are profile
settings with bounded validation. Intentional impossible requests never execute.

Timeouts default to 900 seconds for capacity, 120 seconds for admission once
matching free capacity is usable, and 300 seconds idle plus 300 seconds retirement
margin. Admission accounts for existing Pod requests; quota-wait time is not
misreported as immediate admission failure. Overall scenario waits remain bounded.
Storage first records existing PV identities and uses a read-only binding probe;
marker writes and PVC deletion require a fresh, run-bound Delete volume. An
unexpected existing or retained binding is preserved and reported as a failure.

The suite never backdates timers or changes the installed idle setting.

`scale-from-zero` uses the mandatory smoke as its positive proof when preflight
observes zero workers. Smoke otherwise prefers an already Ready unpaused worker,
so it does not create a second worker before an overflow test. Scenarios report
blocked when their initial-state prerequisites are absent.

## Evidence and cleanup

Each run prints its unique directory under `validation/kubernetes/runs/` (ignored
by Git). It contains `run.json` (including source hashes), `profile.json`, `events.jsonl`, `report.md`, `report.json`,
`junit.xml`, and rendered kube-burner templates/configuration/logs. Evidence
contains cluster metadata; keep the directory private. It contains no kubeconfig
or credential copy. The run label is `validation.homelab.tfdraw.dev/run`.

Exit code 0 means the requested scenarios and cleanup passed. Exit code 1 means
failed or blocked/incomplete. JUnit encodes failures as failures, blocked cases as
errors, and unrequested future work as skipped/deferred. No performance thresholds
are imposed. Timing distributions and throughput are observations, not SLO claims.
Raw Kubernetes objects preserve admission/Ready/completion transition timestamps,
placement and related events. Polling latency is bounded by the configured poll
interval plus API time; already Ready nodes have zero observed readiness latency. Their server
creation-to-Ready values include previous node history and are not scale-up
latencies.

Cleanup runs after each scenario and on interruption. It only deletes allowlisted
namespaced objects carrying this run label, with server-side UID/resource-version
preconditions. Status-update conflicts retry at most five times, rechecking UID,
run ownership and storage binding before each retry. Namespaces, Nodes, PVs, queues, and existing storage proof data are
never cleanup targets. Controllers remove their owned dependents by garbage
collection. Run-specific names prevent collisions; resources are created, not
applied over existing objects. Run processes share a per-target local lock.

After a killed process or unavailable API, retry with the **same profile**:

```sh
python3 validation/kubernetes/suite.py cleanup \
  --run-dir validation/kubernetes/runs/kv-0123456789abcdef \
  --profile validation/kubernetes/runs/kv-0123456789abcdef/profile.json
```

A retry preserves the original failure in the report. Inspect unresolved cleanup
failures; never remove finalizers, controller journals, or foreign resources to
make a result pass. Explicit consolidation uses the existing controller's scope,
locks and eviction checks; the suite refuses plans containing foreign Pods.
Returning Job demand reopens the controller's owned primary cordon.

## Future work and approval boundaries

[`coverage.json`](coverage.json) is the machine-readable future coverage matrix:
every entry has a prerequisite, eventual acceptance test, and GitHub issue.
[Issue #113](https://github.com/TusharSariyaOrg/aws-account-infra/issues/113) tracks
the remaining gaps and reuses the earlier proof/decision issues. A closed proof
issue documents a narrow capability, not completion of its generalized version.

This reconciles the deferred items in the pilot's
[autoscaling design](https://github.com/TusharSariyaOrg/aws-account-infra/blob/cd48f53/docs/plans/homelab-autoscaling-iac.md),
[operations plan](../../docs/plans/talos-two-worker-operations.md), and
[production roadmap](../../docs/plans/production-kubernetes-homelab-roadmap.md).
Physical shutdown awaits service migration; generalized lifecycle, app policies,
CI/schedule/URL demand, automatic consolidation, cross-host stateful placement,
production budgets, performance gates, larger stress and conformance remain future
work. The explicit durability deferral in [#39](https://github.com/TusharSariyaOrg/aws-account-infra/issues/39)
still applies to backup/restore and outage/redundancy drills. GitHub/Tailscale
outage independence is not a current requirement. The deferred secondary cache
and production migration approvals remain unchanged.

## Local verification

```sh
python3 -m unittest discover -s validation/kubernetes/tests -v
uvx ruff@0.12.12 check validation/kubernetes
uvx ruff@0.12.12 format --check validation/kubernetes
```

CI performs these checks and validates rendered load manifests. It has no cluster
credentials and never starts a live run. Test fixtures cover delayed capacity,
admission timeout, cancellation, missing prerequisites, interrupted cleanup and
foreign-resource protection.

Kube-burner is pinned to 2.8.5, including the installer archive SHA-256. Configuration
fields follow the [pinned source](https://github.com/kube-burner/kube-burner/blob/v2.8.5/pkg/config/types.go)
and [upstream reference](https://kube-burner.github.io/kube-burner/latest/reference/configuration/).
Both global/job garbage collection and job cleanup are disabled: even its `gvr`
strategy eventually deletes namespaces and is unsuitable for this shared namespace.

The initial live results and development failures are recorded in
[the pilot evidence](evidence/2026-09-21-pilot.md).
