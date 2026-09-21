# Idle retirement and fresh-worker recreation

This bounded integration connects the idle observer to the existing guarded
retirement path for primary prototype VM 9107. Secondary retirement is excluded
because its retained-volume ownership has a separate migration path. Neither
service can power off a physical host.

## Configurable window

Both `prototype-consolidation` and `prototype-primary-lifecycle` read the optional
file `~/.config/homelab-capacity/lifecycle.env`:

```sh
HOMELAB_IDLE_SECONDS=300
```

The default without this setting is 1800 seconds. The deployed prototype uses
300 seconds (five minutes), as requested for testing. Values must be positive
whole seconds. After editing the file, restart both services:

```sh
systemctl --user restart prototype-consolidation prototype-primary-lifecycle
```

Changing the window starts a fresh timer rather than reusing elapsed time from
another configuration. The observer records `idleSeconds`, `idleSince`, and
`deadline`. Retirement rejects stale observations or mismatched settings, so
restarting only one service cannot silently shorten an existing window.

## Lifecycle and commit boundary

1. Explicit consolidation leaves an empty worker with an owned cordon. Automatic
   consolidation is not enabled. The observer measures the configured idle window.
2. The primary lifecycle service sees eligibility and invokes guarded retirement.
   Under the shared slot lock, it verifies node/VM generation and checks the
   complete window, Ready state, owned cordon, active workloads, pending demand,
   VolumeAttachments, and the absence of a `slot-primary/maintenance` file.
3. The same checks run again after draining and immediately before the graceful
   Talos shutdown. New demand before this boundary cancels retirement and reopens
   only the controller's cordon.
4. A `shutdown-committed` journal is atomically written before sending shutdown.
   Demand arriving after that point is latched in `rewakeQueued`; the controller
   finishes deleting only the verified, stopped, disposable VM generation.
5. Retirement records target zero. If demand was latched, it records target one
   before releasing the lifecycle lock. Otherwise later autoscaler demand can set
   target one. The service then runs the existing create/join reconciler and
   publishes a fresh worker, with a new VM hardware identity and Kubernetes UID.

The journal is `slot-primary/retirement.json` below
`~/.local/share/homelab-capacity`. An interrupted check, shutdown, or creation, or
an uncertain API result, becomes `blocked`. The service never automatically
retries destructive recovery. Inspect the journal, VM generation, and node
state before any manual recovery; do not simply erase the journal.

The older `prototype-primary-reconciler` is disabled and inactive. This supervisor owns
subsequent primary recreation, using the same lock as autoscaler requests and
retirement. Secondary's reconciler and CSI ownership are unchanged. Physical
power-off remains blocked while production guests run on both hosts.

## Verification

Tests exercise young/stale/mismatched windows, changed node identity, busy
workers, attached storage, maintenance, foreign cordons, demand during draining,
demand after shutdown, creation failures, interrupted operations, and secondary
exclusion. The integration tests run the actual retirement function with fake
external APIs and verify that precommit cancellation never issues shutdown.

The live proof uses the complete configured five-minute window. Its fixtures
submit a Kueue Job constrained to the primary slot after the shutdown commit;
no timer backdating or duration bypass is part of the implementation.

This remains an isolated prototype. Production packaging, a broader application
policy API, automatic consolidation selection, host-service migration, physical
shutdown, and operator recovery procedures remain separate work.

The observed automatic shutdown commit occurred 316.3 seconds after the idle
window began: five minutes plus polling and guard checks. The incoming Kueue
Workload was then latched as `rewakeQueued: true` while shutdown was committed.
See [idle observation](idle-start.json), [commit time](shutdown-commit.json),
and [queued demand](queued-after-commit.json). No physical host power-off was
issued.

The queued Job ran on fresh node `talos-ub2-gx6`, 200.2 seconds after the shutdown
commit. Both the Kubernetes UID and VM hardware UUID differ from the retired
worker ([before](before.json), [after](after.json), [events](events.json),
[summary](summary.json)). The test Job is removed after this check. The primary
lifecycle service remains enabled with a five-minute window; the fresh worker is
uncordoned. The retirement journal's `name`/`uid` identify the retired generation;
`slot-primary/observed.json` identifies the current worker.

Validation: 110 Python tests, Go tests, Helm lint, and the prototype Trivy
HIGH/CRITICAL scan pass. Production nodes remained Ready; the retained-volume
marker on secondary remains Running. The lifecycle service had no automatic
restarts during the proof and peaked at about 37 MiB memory.
