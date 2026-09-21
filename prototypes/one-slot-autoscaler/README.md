# One-slot external-gRPC autoscaler prototype

Throwaway scale-up integration for [issue106](https://github.com/TusharSariyaOrg/aws-account-infra/issues/106). The runtime owns only secondary prototype VM9105 and empty template9106. Production VMs100/102/103 and retained-volume prototype9104 are excluded. Deletion and physical shutdown RPCs are disabled.

The subsequent [Kueue extension](kueue/README.md) adds suspended-Job capacity requests and negative fit checks to this same isolated provider. The ordinary-Job evidence below describes the earlier baseline.

## Boundaries

- Upstream Cluster Autoscaler1.36.1 runs through the included Helm chart in the isolated `laptop-wifi-PROTOTYPE` cluster. Its image is pinned by digest; scale-down is disabled.
- The small Go service implements upstream external-gRPC protobufs, accepts a single zero-to-one request and atomically records desired size. Calls do not wait for host/VM boot. It advertises one group with min0/max1 and conservative allocatable capacity (1.8CPU,3GiB,15GiB ephemeral). Production fit budgets are not inferred from this small prototype.
- A Python reconciler on the Ubuntu laptop consumes desired state, invokes the pyghmi power adapter, waits for PVE, creates the guest, enrolls a fresh Talos identity, and waits for Node Ready plus an actual ready CSI Pod and registered CSI driver. It publishes the workload selector label only after these prerequisites pass.
- The secondary PVE helper is reachable only through a dedicated laptop key with an OpenSSH forced command and forwarding/PTY restrictions. Its only operations are `inspect` and `ensure` for the two fixed prototype IDs/names. It cannot delete guests or run arbitrary commands.
- VM9105 is cloned with a full disposable OS disk from an empty template, then installed from the existing Talos1.13.9 ISO. The template contains no installed Talos identity. This proves orchestration and fresh enrollment, not an optimized preinstalled image pipeline.
- The helper captures a DHCP ACK for the exact prototype MAC to discover the assigned address; it never guesses an unused LAN address. Existing prototype worker configuration supplies the route to the laptop control plane.

The physical secondary host is already running production workloads. `ensure_on` therefore exercises the already-on path; this test does not turn off that host or claim cold physical scale-to-zero. The previous operator startup and independent volume proof remain separate evidence.

## Transport, credentials and process lifetime

CA connects to the laptop provider at10.0.0.181:50051 using mutual TLS. Prototype CA/server/client certificates are private, valid30days, and never committed. Client credentials live in Secret `prototype-slot-client`. Missing/invalid certificates fail closed. Certificate rotation and production deployment are subsequent IaC work.

The laptop runs the provider and reconciler as memory-limited systemd user services. Lingering is enabled for user `tushar`, so logout no longer stops the provider. State is under `~/.local/share/homelab-capacity/slot-state`, configuration/keys under `~/.config/homelab-capacity`. The reconciler handles one scale-up transition and exits; it is not yet the production continuous lifecycle controller. Failures remain visible and do not trigger destructive retries.

Secondary PVE has `/usr/local/sbin/prototype-pve-slot` and root-owned `/var/lib/prototype-slot` DHCP evidence. Existing CSI credentials gained disk-config access only for VM9105; the temporary return route `10.0.2.15/32 via10.0.0.181 dev vmbr0` was restored for controller-to-PVE traffic. No primary route, production CSI, or production worker ownership changed.

## Reproduce on the prepared isolated environment

1. Build `go build .` here (Linux amd64 for the laptop); install the power package from `controllers/homelab-capacity` with its lockfile.
2. Provision separate credentials, strict known-host files, mTLS material, the fixed PVE helper and its forced-command key. The laptop's existing private prototype Talos/kubeconfig files are required.
3. Install the checked-in user units and enable lingering. Start with no VM9105 and target0; never reset state to zero over an existing owned VM.
4. Install `chart/` using Helm and the isolated kubeconfig, after creating the mTLS client Secret. Existing Helm RBAC is part of the chart.
5. Apply `demand-job.yaml`. Observe `TriggeredScaleUp`, desired target1, provisioning phases, the fresh node and Job completion. No Kueue admission policy is installed by this manifest.

The second run must start after an explicit guarded teardown: pause CA/provider/reconciler, remove the test Job, verify no VolumeAttachments, drain and cleanly stop only VM9105, inspect every disk reference, delete only its own disposable disk/VM, remove its Kubernetes node, then reset prototype target state. VM9104's retained data must not be touched. This manual test teardown is not an implementation of automatic scale-down.

Live results are recorded in [evidence.md](evidence.md), with machine-readable Kubernetes observations in [evidence.json](evidence.json).

## Verification and limits

`go test ./...` checks group/instance ownership, duplicate size requests, deletion refusal and the node-template protobuf. Python readiness tests cover the CSI creation/registration race. Power adapter tests cover transport result validation and safe idempotence. Helm lint validates the chart.

Follow-on work remains: ordinary unsatisfiable-demand cases beyond the Kueue extension, two-slot placement, retained storage through the runtime deletion path, per-app policy, one30-minute idle window, cancellation/maintenance coordination, power-off guards and phased OpenTofu ownership migration. Production deployment is not complete.

Vendored generated protobuf files come unchanged from Kubernetes Autoscaler tag `cluster-autoscaler-1.36.1`, commit `6f44b4d18e49ca03e14f9d2637d769570c4acab7`, under the Apache2.0 notices retained in each file. [Upstream provider contract](https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-1.36.1/cluster-autoscaler/cloudprovider/externalgrpc/README.md).
