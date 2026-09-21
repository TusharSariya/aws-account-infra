# Policy-aware consolidation pilot

The laptop can explicitly move an opted-in, stateless Deployment from the primary
prototype worker to secondary. A separate observer persists one 30-minute idle
eligibility window and reopens controller-owned cordons when pending Pods or
Kueue Workloads arrive. It never retires a VM or powers off a host.

## Scope and safeguards

- Exact prototype provider IDs, isolated cluster/context, node UIDs and resource
  versions bind mutations to the observed generation. Shared lifecycle locks
  serialize this path with worker creation and explicit retirement.
- Only ReplicaSets owned by existing Deployments in `prototype-consolidation`
  are candidates. Pods must explicitly annotate `prototype.homelab/allow-move:
  "true"`. `prototype.homelab/policy` accepts `scheduled`, `on-invoke`,
  `persistent`, or `experimental` (default). Persistent workloads and active
  Jobs block movement. The pilot does not implement a general application policy API.
- PVCs, host storage, unsupported volumes or placement constraints, missing
  requests, pending demand, foreign cordons, unhealthy nodes, and insufficient
  destination CPU/memory/ephemeral storage or Pod slots block consolidation.
- PDB status is checked before eviction. The Kubernetes Eviction API remains
  authoritative, using Pod UID/resource-version preconditions. There is no
  force-delete fallback. Each replacement must become Ready on the destination;
  failed movement attempts reopen only this controller's cordon.
- Idle eligibility requires an empty, Ready, controller-cordoned worker without
  VolumeAttachments or queued demand. Known infrastructure DaemonSets are excluded.
  A replacement node, clock rollback, or observation gap over 45 seconds starts
  a fresh window. API errors cannot authorize retirement.
- State lives in `~/.local/share/homelab-capacity/consolidation/idle.json` and is
  atomically replaced. New demand clears the timer. Post-commit queued re-wake
  semantics are unit-tested only; no shutdown actuator is connected here.

## Laptop commands

Use the existing private prototype kubeconfig and scoped laptop runtime:

```sh
export PYTHONPATH="$HOME/.local/share/homelab-capacity/source/src"
python="$HOME/.local/share/homelab-capacity/venv/bin/python"
controller="$HOME/.local/share/homelab-capacity/consolidate.py"
"$python" "$controller" plan
"$python" "$controller" apply --source primary --destination secondary
"$python" "$controller" observe
systemctl --user status prototype-consolidation
```

`apply` is explicit. The installed user service only observes idle eligibility and
cancels owned cordons; it does not automatically move workloads. Test manifests
are disposable fixtures, not production application configuration. Seed one app
per worker using temporary cordons, then restore those cordons. `workloads.yaml`
starts with a blocking PDB; patch its `minAvailable` to zero only for the movement
proof. `demand.yaml` is the Kueue job that demonstrates cancellation.

## Observed proof (2026-09-21 UTC)

1. One 500m Deployment ran on each worker. `protect-b` prevented consolidation;
   the explicit apply failed and both Pod UIDs remained unchanged
   ([blocked decision](pdb-blocked.json), [unchanged identities](blocked-apply.json)).
2. With test disruption permitted, the Eviction API accepted movement. Both
   Deployments became Ready on secondary and primary was controller-cordoned
   ([apply](applied.json), [placement](placement.json)).
3. Primary entered the persisted idle window. Secondary stayed ineligible due
   to active workloads and its retained-volume attachment ([idle](idle-started.json)).
4. A queued 1-CPU Kueue job cleared primary's timer, reopened it, and ran there
   while the apps stayed on secondary ([cancellation](demand-canceled-idle.json)).
5. The final eviction/wait path repeated successfully, and queued demand again
   reopened primary ([repeat move](repeated-apply.json),
   [repeat cancellation](repeated-cancellation.json)).
6. Controlled-clock tests verify 1790 seconds remains idle, 1800 seconds reaches
   eligibility, new demand cancels before commit, and demand after a simulated
   shutdown commit is latched for re-wake. No 30-minute physical shutdown test ran.

Both hosts still run production guests ([inventory](running-host-guests.json)).
Physical shutdown is disabled unconditionally. Host-service migration, runtime
retirement integration, broader workload policies and production packaging are
still separate work. Test workloads are removed after the proof; prototype
workers and the existing retained-storage marker remain available.

Validation: 80 Python tests, the Go test suite, Helm lint, and the prototype
Trivy HIGH/CRITICAL scan pass. Production nodes remained Ready. The observer
used about 11 MiB resident memory with a measured peak near 35 MiB.
