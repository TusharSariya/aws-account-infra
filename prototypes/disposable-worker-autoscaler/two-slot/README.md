# Two-endpoint placement prototype

Extends the earlier one-slot proofs for [issue 109](https://github.com/TusharSariyaOrg/aws-account-infra/issues/109). Only isolated prototype resources are managed; production VM ownership remains unchanged.

## Inventory and boundaries

| Slot | PVE endpoint | Worker/template | Runtime state | Storage capability |
| --- | --- | --- | --- | --- |
| Secondary | 10.0.0.223 / pve | 9105 / 9106 | slot-state | Tested retained CSI path |
| Primary | 10.0.0.224 / pve | 9107 / 9108 | slot-primary | Stateless pilot only |

Each slot is min 0/max 1 and uses a separate lifecycle lock. The provider matches full endpoint-domain/VM identity, not the non-unique node name `pve`. Root-owned `/etc/prototype-slot.json` selects the primary helper inventory; missing configuration preserves the original secondary inventory. The SSH caller cannot supply an arbitrary VM ID. The dedicated laptop public key is constrained by the same forced-command helper on both endpoints; host trust is pinned.

Primary uses the same pinned Talos ISO, fresh 24-GiB OS template/clone and a distinct MAC. Its pilot is 2 vCPU / 4 GiB; this is not a production worker-size decision. Existing primary guests reserve 116 GiB, so the extra 4 GiB leaves about 5.8 GiB of physical memory outside configured guest maxima. The pilot does not constitute a CPU load test or a production overcommit budget.

Primary advertises no CSI capability and does not receive CSI privileges. It publishes shared-pool eligibility after Node Ready; secondary still waits for CSI readiness too. Existing retained-volume topology remains secondary-only. Primary CSI and two-host stateful placement are separate gates.

## Placement behavior

Both templates and eligible nodes advertise `prototype.homelab/pool=workers`. The shared Kueue queue has conservative aggregate pilot quotas of 3 CPU, 4 GiB memory and 20 GiB scratch; quotas remain attainable capacity, not a measurement of currently free disk space.

CA first considers fit on existing nodes. For expansion among eligible groups, the laptop `placement.py` reads IMM2 power and updates the priority-expander ConfigMap every 30 seconds: known-on above known-off, unknown below both, secondary as a deterministic tie-break. Priorities are advisory and can become stale if the publisher fails; the power adapter still re-observes actual state before any wake and never equates unknown with off. The two-slot test uses hosts already powered on; sleeping-host rank behavior is unit-tested, not a cold physical-wake proof.

The opt-in `homelab-binpack` scheduler is upstream kube-scheduler v1.36.3 pinned by digest. `NodeResourcesFit/MostAllocated` with CPU/RAM weights and a dominant score weight prefers the busier fitting node. Hard constraints still filter candidates. It schedules only Pods selecting that scheduler name; existing default-scheduler workloads are unaffected. Its service account uses upstream scheduler/volume/authentication roles. It runs on the laptop control plane with bounded resources.

This packs new work; it does not migrate existing Pods. Automatic CA deletion, policy-driven evictions, the shared 30-minute idle timer and physical shutdown remain disabled. Production guests on both hosts are real shutdown blockers until ownership/migration work is complete.

## Prepared test sequence

Install the updated provider/helper and separate primary reconciler user unit. Start the read-only power preference publisher. Upgrade the parent Helm chart (including opt-in scheduler), then apply `queue.yaml`.

1. `first-job.yaml` requests 1200m CPU and fits the already-ready secondary. Verify primary target stays zero.
2. `overflow-job.yaml` requests another 1200m CPU. Combined demand cannot fit one pilot worker; verify exactly the primary slot creates a fresh worker and the overflow Job runs there.
3. Cancel only the overflow test Job. Keep the first Job running, then apply `packed-job.yaml` with two 150m Pods. Verify both land on the busier secondary while primary remains available.
4. Remove only these test Jobs after capturing evidence; retain both workers and the existing marker volume for inspection. No automatic retirement is enabled by this test.

## Sources

- [Pinned CA priority expander contract](https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-1.36.1/cluster-autoscaler/expander/priority/readme.md)
- [Kubernetes resource bin packing](https://v1-36.docs.kubernetes.io/docs/concepts/scheduling-eviction/resource-bin-packing/)

Recorded live results: [evidence.md](evidence.md).
