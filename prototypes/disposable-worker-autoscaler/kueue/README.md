# Kueue admission extension

Isolated follow-on to the ordinary Job proof, tracked in [issue 107](https://github.com/TusharSariyaOrg/aws-account-infra/issues/107). Only the `laptop-wifi-PROTOTYPE` cluster and VM 9105 are in scope.

## Contract

Kueue 0.19.4 chart digest `sha256:a11f1ab76d9133d8ae7cbcfbd0ad6a5ee5cb4494831144ceef09688f6738dc9d` and the image digest in `values.yaml` are pinned. The controller runs on the laptop control plane with a 512-MiB memory limit, a 256-MiB request and only the batch Job integration enabled in namespace `prototype-slot`. Upstream cert management supplies webhook certificates.

The ClusterQueue offers attainable quota even at zero workers: 1500m CPU, 2 GiB RAM and 10 GiB ephemeral storage. These conservative prototype quotas leave room below the provider template; they are not production RAM/scratch budgets or fresh filesystem admission validation. The ResourceFlavor targets the slot label, never a disposable hostname. `managedResources` includes CPU, RAM and scratch rather than a GPU-only example.

Kueue reserves quota and creates a ProvisioningRequest while the Job is suspended. CA uses `best-effort-atomic-scale-up.autoscaling.x-k8s.io` to request capacity. Its `Provisioned=True` acknowledges successful scale-up submission; it must not be treated as Node/CSI readiness. The existing reconciler publishes the slot selector only after those prerequisites pass, keeping the admitted Pod pending until usable capacity exists.

The autoscaler chart enables ProvisioningRequests and adds their RBAC plus read-only PodTemplate access. The vendored CRD is unchanged from upstream autoscaler tag `cluster-autoscaler-1.36.1`, path `cluster-autoscaler/apis/config/crd/autoscaling.x-k8s.io_provisioningrequests.yaml`.

## Prepared-environment sequence

Use the isolated kubeconfig for every command. Apply `provisioningrequest-crd.yaml` with server-side apply before starting CA with its new flag. Install the Kueue chart at version 0.19.4 with `values.yaml`, wait for its webhook/controller readiness, then apply `queue.yaml`. Upgrade the parent autoscaler Helm release.

After the guarded manual teardown described in the parent README, verify the owned VM is absent and desired size is zero. Apply `over-quota-job.yaml` and `unfit-job.yaml` first. The first cannot reserve quota; the second can reserve quota but cannot satisfy its hardware selector. Both must remain suspended with no Job Pods and no provider scale-up. Capture several autoscaler loops before deleting these test Jobs.

Apply `job.yaml` and capture Workload quota/admission conditions, ProvisioningRequest status, provider phases, fresh node identity and Job completion. Keep automatic deletion/physical shutdown disabled. Tests run against an already-powered-on host, so this does not prove cold host wake.

## Sources

- [Kueue v0.19 ProvisioningRequest](https://kueue.sigs.k8s.io/v0.19/docs/concepts/admission_check/provisioning_request/)
- [Pinned CA class semantics and RBAC](https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-1.36.1/cluster-autoscaler/FAQ.md#how-can-i-use-provisioningrequest-to-run-batch-workloads)

See [negative-evidence.json](negative-evidence.json) for the 74-second rejection observation. See [evidence.md](evidence.md) and [evidence.json](evidence.json) for the successful 213-second scale-up and its limits. No production queue or CI routing is changed by these manifests.
