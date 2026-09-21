# Pilot autoscaler latency

`autoscaler.py` changes only the pinned `prototype-slot-ca` provisioning backoff
and scan interval. It retains the existing provider, worker limits, placement,
scale-down setting and image. It verifies the cluster identity and image before
patching and saves original arguments privately for restoration.

```sh
python3 ~/pilot-platform/controllers/autoscaler.py tune
python3 ~/pilot-platform/controllers/autoscaler.py restore
```

The current experiment uses a 2-second initial / 5-second maximum provisioning
backoff and a 2-second scan interval. The original was 10 / 30 seconds with the
default 10-second scan interval. Faster retries trade more controller/API work for
lower admission latency; the bounded load suite and capacity gates must verify it.
The baseline and in-cluster monitoring suites passed with this combination.
With Argo installed, the workload suite also passed, but the independent host
paging gate failed; Argo was removed. See the
[capacity and rollout evidence](../monitoring/evidence/portable-preflight.md).

The 16-Job admission timeout reproduced on the original VM with host monitoring,
so it is not specific to moving monitoring into Kubernetes. A single 16-Job
reproduction also failed. Captured requests remained Pending between retries even
as earlier jobs completed; source inspection shows capacity reservations and
retry timing are separate from physical Pod resource accounting. Shorter backoff
alone did not pass. The combined 2-second scan / 2-to-5-second backoff passed run
`kv-3d21ac677f9577fa`, including cleanup. See
[the bounded report](../monitoring/evidence/tuned-bursts-20260921.md).
This verifies the timing improvement on this pilot; it does not claim an upstream
autoscaler bug or change the 120-second acceptance deadline.

Primary source: [pinned autoscaler retry logic](https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-1.36.1/cluster-autoscaler/processors/provreq/injector.go)
and [reservation processing](https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-1.36.1/cluster-autoscaler/processors/provreq/processor.go).
