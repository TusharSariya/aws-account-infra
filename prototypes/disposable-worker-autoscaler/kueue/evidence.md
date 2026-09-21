# Kueue zero-worker evidence

Observed September 20, 2026 local time (September 21 UTC) for [issue 107](https://github.com/TusharSariyaOrg/aws-account-infra/issues/107).

## Successful transition

The suspended Job `kueue-zero-to-one-proof` reserved quota and created a ProvisioningRequest before producing a Pod. Cluster Autoscaler accepted that request and changed `prototype-secondary` from zero to one. The laptop reconciler created VM 9105, installed Talos with fresh node identity `talos-2cq-i7z`, waited for Node Ready and CSI registration/readiness, then published its workload selector.

The Job was created at 01:27:00 UTC and completed at 01:30:33 UTC: **213 seconds (3m33s)**. The Workload reports Admitted and Finished. [Machine-readable evidence](evidence.json) records the initially suspended Job, admitted-but-pending Pod during boot, successful ProvisioningRequest snapshot and completed Job/node identity. Kueue removed the ProvisioningRequest after completion; the successful request status was captured during boot, not reconstructed afterwards.

CA set Provisioned=True at scale-up submission before the node existed. This confirms why that status must not substitute for worker readiness. The new node initially lacked the slot selector and the Job stayed Pending. Execution followed the reconciler's CSI readiness gate.

## Rejection checks at zero

For 74 seconds, including repeated CA processing, both negative Jobs remained suspended and created no Job Pods. Desired provider size stayed zero:

- A 4-CPU Job exceeded the prototype's 1500m quota. Kueue did not reserve quota or create a ProvisioningRequest for it.
- A small Job with an unsupported hardware selector reserved quota, but CA reported CapacityIsNotFound and did not request a worker. The request stayed pending for re-evaluation.

The negative Jobs were deleted before the valid run. [Negative snapshots](negative-evidence.json) preserve the quota and provisioning conditions. This is a bounded observation, not a claim about arbitrary unsatisfiable workloads or indefinite retry behavior.

## Validation and footprint

Helm lint, server-side dry runs of queue/negative manifests, and the prototype Trivy HIGH/CRITICAL scan passed. The live proof validates the added flag, CRD, RBAC, Kueue configuration and queue manifests together. No provider or power protocol code changed.

An idle kubelet stats snapshot measured Kueue working set 77,467,648 bytes (73.9 MiB) and CA 28,536,832 bytes (27.2 MiB). The laptop had about 2.2 GiB available and zero swap used. These are point-in-time observations, not load-tested controller budgets; Kueue has a 512-MiB limit.

Production control plane and both workers remained Ready. The retained-volume prototype 9104 remained stopped and untouched. Only the previous disposable VM 9105 was manually drained, stopped and destroyed after identity/disk/attachment checks to prepare this fresh cycle.

## Remaining scope and live state

Kueue and CA remain running on the laptop control plane; the provider remains active and the one-transition reconciler exited successfully. VM 9105 remains running with the completed proof Job. Automatic deletion and physical shutdown remain disabled. Physical hosts were already on.

Next gates are retained-storage survival through the actual runtime deletion path, two-slot placement/consolidation, per-app policy and safe shutdown. Production RAM/scratch quotas, ARC integration, cold host wake, IaC ownership migration and load testing are not claimed complete by this prototype.
