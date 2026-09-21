# One-slot scale-up evidence

Observed September 20, 2026 local time (September 21 UTC), for [issue 106](https://github.com/TusharSariyaOrg/aws-account-infra/issues/106).

## Result

A normal pending Kubernetes Job triggered upstream Cluster Autoscaler through the laptop external-gRPC provider at zero prototype workers. The reconciler verified secondary IMM2 power, created VM 9105 from empty template 9106, installed Talos, enrolled a fresh node, waited for networking and CSI readiness, and released the workload selector. The Job succeeded.

The repeat run started at 01:11:32 UTC and completed at 01:14:54 UTC: **3 minutes 22 seconds**. Its fresh node was `talos-390-cu5`, provider ID `proxmox://prototype-secondary/9105`. Captured Job status, node identity and scale-up events are in [evidence.json](evidence.json).

## Repeatability and readiness correction

The first cycle created node `talos-3k8-ghb` and completed the Job, but exposed a reconciler race: waiting for a CSI Pod failed before the DaemonSet had created that Pod. The corrected reconciler polls both ready CSI Pods and CSINode driver registration, and publishes the workload selector only afterwards.

For the repeat, the test Job was removed and the first node drained and cleanly stopped. Before destroying only VM 9105, its identity, stopped state, absence of VolumeAttachments and ownership of every disk reference were checked. The previous node was removed and prototype desired state reset. The second cycle produced a different node identity; its Job remained pending while CSI started and succeeded after readiness. Restarting the reconciler against that existing VM returned ready successfully without duplicate creation.

## Power adapter and checks

- pyghmi 1.6.19 authenticated from the laptop to both IMM2 controllers with the separate restricted `capacity` account. Structured status and idempotent ensure-on succeeded.
- Paramiko 4.0.0 also authenticated; Paramiko 5 cannot supply the legacy RSA signature required by these controllers. SSH remains an operator/diagnostic path.
- 31 Python tests passed across power behavior and CSI readiness; three Go tests passed for group ownership, bounded scale requests and protobuf behavior. Helm lint passed.
- Production nodes `talos-cp-01`, `talos-worker-01` and `talos-worker-02` were all Ready after the proof. Protected VMs 100/102/103 and retained-volume prototype 9104 were excluded from provisioning and teardown.

The repository security check subsequently caught unused endpoint-write RBAC inherited from the upstream example and a missing read-only root filesystem on the proof Job. Endpoint writes were removed (leader election is disabled), the Job was hardened, and the Helm release was updated. The hardened Job completed on the existing worker. The captured JSON above remains the earlier zero-to-one run, not this final manifest check.

## Deliberate limits and live state

Both physical hosts were already powered on. This proves the already-on power path, not a pyghmi off-to-on cycle or physical scale-to-zero. Automatic deletion and physical shutdown are disabled. Kueue admission, two-slot placement, runtime retained-volume deletion, app policies and production migration remain subsequent work.

VM 9105 is left running with a completed test Job. Template 9106 remains available. The laptop provider is active as a bounded systemd user service; the single-transition reconciler exited successfully. The older storage prototype 9104 remains intentionally stopped. Prototype mTLS credentials expire after 30 days and are held outside Git. This is isolated integration evidence, not a production deployment.
