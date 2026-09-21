# Paused hosts and queued-demand cold start

This pilot adds an explicit operator pause/resume boundary. A manual host shutdown
preserves its VMs; resuming that known state starts the preserved primary worker.
Ordinary idle scaling still deletes and recreates disposable workers through the
separate lifecycle integration. This path never deletes or reconfigures a VM.

## Pause and resume

On the prepared laptop:

```sh
export HOMELAB_PROTOTYPE_SLOT=primary
export PYTHONPATH="$HOME/.local/share/homelab-capacity/source/src"
python="$HOME/.local/share/homelab-capacity/venv/bin/python"
control="$HOME/.local/share/homelab-capacity/capacity_control.py"
"$python" "$control" pause --slot all
"$python" "$control" resume --slot primary
```

Pause persists `maintenance` files in both slot state directories. The command
acquires every requested lifecycle lock before writing any pause marker; an
in-flight operation must finish first. It does not shut down a host or interrupt
a committed retirement. The autoscaler rejects paused expansion, the reconciler
rejects paused provisioning, and the observer does not reopen paused cordons.
The lifecycle supervisor checks pause before retirement, recreation, or cold start.
Services may stay enabled while paused, including across laptop reboots.

Resume is currently implemented only for primary. It requires a preserved target
of one, an owned node identity, a confirmed powered-off host, and no uncertain or
unfinished operation. It records the expected Kubernetes UID and VM hardware UUID,
then removes only primary's pause marker. It does not immediately power on a host.
Secondary remains paused. To run the supervisor after previously disabling it:

```sh
systemctl --user enable --now prototype-primary-lifecycle prototype-consolidation \
  prototype-slot-provider prototype-slot-placement
```

The legacy one-shot reconciler units remain disabled. The idle window remains
configured to five minutes through the shared `lifecycle.env` file.

## Demand and boot boundary

The first cold-start recognizer is deliberately narrow: one Pod in a Kueue
Workload from `prototype-slot` / `prototype-shared`, pinned to the primary worker
pool and using `homelab-binpack`. CPU, memory and ephemeral-storage requests must
fit the existing conservative slot budget; unsupported placement, persistent
storage, extended resources, inactive/finished workloads, and other queues do not
trigger this pilot. General demand selection is not implemented by this recognizer.

A matching request causes the laptop to wake primary through the existing IMM2
adapter. It waits up to 15 minutes for PVE, verifies the preserved VM generation,
starts it through the scoped helper, checks the generation again, waits for Node
Ready, and reopens that exact node using UID/resource-version preconditions. It
never uses insecure Talos configuration enrollment for a preserved VM.

The journal is `slot-primary/cold-start.json`. Unknown power results, changed or
missing generations, or an interrupted wake become `blocked`, requiring operator
review. Retrying destructive recovery is not part of this pilot. Other controllers
or administrators must not mutate the prototype VM during a lifecycle operation.

Powering primary also starts its existing production VMs according to their PVE
onboot settings. Secondary remains off in this test, so this is not a claim that
the entire production cluster has been restored. Physical host power-off remains
an explicit operator operation until the remaining host-service migration work.

## Proof

The test Job was submitted while both hosts were off. Both remained off with the
supervisor, observer and provider running, and the Job stayed suspended
([paused state](paused.json)). The explicit primary resume recorded a preserved
identity and armed demand detection ([resume](resume.jsonl)). The same Job then
triggered primary's wake; secondary stayed paused.

The fixture is [demand.yaml](demand.yaml). This manual-stop recovery preserves VM
and node identity; the earlier [idle lifecycle proof](../lifecycle/README.md)
separately demonstrates fresh identities after disposable-worker retirement.

## Capacity-request retry correction

The first live run exposed a separate admission delay: the worker was Ready but
Kueue still held the Job suspended. A read-only check reproduced that exact state.
Cluster Autoscaler 1.36.1 exponentially backs off failed ProvisioningRequests,
starting at one minute and capping at ten minutes. The request had failed during
hardware boot, so new Ready capacity did not cause an immediate retry. Node labels,
requests, and taints were correct.

The prototype Helm values now set `provisioningRequestInitialBackoff: 10s` and
`provisioningRequestMaxBackoff: 30s`. These are capacity-check retry intervals,
separate from the five-minute idle window. No Kueue admission status was patched
and no Job was manually unsuspended. The original queued Job ran after deploying
this configuration. A second live fixture tests the retry cap after capacity is
unavailable for multiple retry cycles, then becomes schedulable again.

Upstream source for the pinned version:
[retry algorithm](https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-1.36.1/cluster-autoscaler/processors/provreq/injector.go),
[flag defaults](https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-1.36.1/cluster-autoscaler/config/flags/flags.go).
The [read-only admission check](check-admission.py) is the integration regression
seam; a unit test imitating upstream backoff would not exercise this failure.

The cold-start worker became Ready in 271 seconds from the queued wake request,
with its original VM and node identities ([worker proof](ready.json)). Primary
was on and resumed; secondary was still off and paused ([power state](after-power.json)).
The follow-up test held capacity unavailable for 70 seconds, then the Job reached
Running 27.4 seconds after uncordoning ([retry evidence](retry-evidence.json)).
The original red admission check became green, and the follow-up fixture passed
the same check. Both test Jobs are removed after verification.

Validation: 131 Python tests, six Go tests, Helm lint, and the prototype Trivy
HIGH/CRITICAL scan pass. The production control plane and primary worker returned
Ready through their existing host autostart behavior; secondary is intentionally
off. Automatic physical shutdown remains disabled.
