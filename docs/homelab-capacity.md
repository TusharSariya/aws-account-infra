# Shared storage foundation

This is stage 1 of `add-homelab-workload-scheduling`. It does not migrate, reset or stop the current AI workloads. The capacity release defaults to disabled until trusted identity enrollment and independently managed physical telemetry are ready. Empty status maps are deliberately unhealthy. The lifecycle controller and aggregate AI Pod remain separate later stages; this foundation is not a functioning lifecycle service.

## Reconstructing the foundation

The Proxmox root keeps the original VM resources, disks and backend. Talos retains the original disk selector and XFS partition while adding project quota support and worker user-namespace support. Kubernetes OpenTofu installs `homelab-capacity` using the pinned Python image and embeds the repository Python source as Helm-managed configuration. Source and chart contents participate in the saved plan. Existing local-path provisioning and PVCs remain untouched.

Use the existing PR plan, apply label, protected prod environment and saved-plan apply workflow. Do not use a local Helm install or edit the host outside the recipe. Activating project quota support may require a full remount. Request explicit worker maintenance, retaining the original partition identity and verifying the mount after reboot. A normal no-reboot apply is not evidence that quota enforcement became active.

The helper creates only `ai-models`, `ai-workspace` and `ai-vector` directly beneath `/var/mnt/local-path-provisioner`. Their project IDs are 31001, 31002 and 31003, with hard limits of 300, 20 and 10 GiB. It refuses to relabel occupied or foreign-project directories. These limits do not allocate blocks. It verifies the source device, exact mount, XFS filesystem UUID, accounting, enforcement, inheritance and kernel hard limits on each collection cycle. It has no reset or deletion operation.

The helper uses Linux file-descriptor quota operations, so it does not mount host `/dev`, PID namespaces or container-runtime sockets. Only this helper receives quota capabilities. Its Kubernetes identity can patch only `guest-capacity`; the independent physical collector can patch only `physical-capacity`. Neither can list Secrets or change the other's report.

## Quota escape prevention

An isolated test on Linux showed that a non-root owner in the host user namespace could move an owned file to project zero through `FS_IOC_FSSETXATTR`, escaping the hard limit. Dropped capabilities and root-owned top-level directories alone are insufficient.

All future AI consumers of these static local volumes must use `spec.hostUsers: false`, RuntimeDefault seccomp and dropped capabilities. Talos enables the worker-only user-namespace prerequisite; Kubernetes 1.36 supports the Pod field. Acceptance must verify project-zero changes are rejected from the actual application Pod before migration. Do not expose these volumes to a Pod using the host user namespace. The Linux disposable test checks the user-namespace denial, but does not prove Talos/containerd volume integration.

References: [Kubernetes user namespaces](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/), [quota accounting and user namespaces](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/), [Talos setup](https://docs.siderolabs.com/kubernetes-guides/security/usernamespace).

## Physical capacity credential and host setup

The collector must observe both live thin-pool data and metadata percentages. Proxmox guest disk size and ordinary storage free-space reports cannot replace these measurements. `lvs` is a fixed reporting command; its `--readonly` option is intentionally omitted because that mode does not query live device-mapper state. No API input can choose a command or LVM mutation.

The repository-managed recipe is `scripts/install-homelab-capacity.sh`. It installs a root-only, fixed-command sampler timer and a separate unprivileged HTTPS exporter. The exporter has no capabilities, cannot execute the sampler or write its snapshot, and serves only GET `/capacity`. The timer samples every 30 seconds. Failures replace the snapshot with unhealthy evidence. The exporter preserves the original sample timestamp, so a failed timer cannot create fresh healthy evidence.

Provision a dedicated CA and client identity independently of Proxmox deploy tokens, the Talos identity and application credentials. Keep its CA signing key offline. The host server certificate must include its configured numeric private IPv4 address in SAN and serverAuth usage. Issue the collector certificate with clientAuth usage and a bounded validity period. Keep private keys out of Git, OpenTofu values/state, plans, logs and images. Use a dedicated client CA so unrelated service certificates cannot authenticate.

The host installer expects a protected directory containing:

- `config.json`: exactly `bind` (private Tailscale IPv4) and `pool` (observed `VG/LV` identity).
- `server.crt` and `server.key`: the exporter certificate and private key.
- `client-ca.crt`: only the dedicated collector client CA certificate.

Run the recipe from a reviewed checkout through an explicitly authorized host setup path. It checks prerequisites, copies root-owned files with restricted permissions, installs the sampler/exporter systemd units and verifies service activity. Re-running it reconciles files and services without touching disks or data. The repository does not currently have a protected CI host-install SSH identity; provisioning and CI verification of that path remain outstanding. Never substitute a Proxmox deployment token as a collector credential.

The physical collector requires a separately reconciled Kubernetes Secret named `physical-capacity-client` in `homelab-platform`, with keys `ca.crt`, `tls.crt`, and `tls.key`. This Secret is mounted only by the physical collector. Its transport must be reachable from the Pod network; a private Tailscale address is not automatically routable from every Kubernetes Pod. Verify routing and mTLS from the collector path before activation. No routing assumption counts as acceptance evidence.

Pin the trusted worker XFS UUID from Talos discovery and the actual physical pool identity in `config/environments/kubernetes/homelab/capacity-values.yaml`. Configure the numeric IPv4 HTTPS endpoint (hostnames are rejected because collector egress deliberately excludes DNS) and its exact private IPv4 `/32` egress rule. The helper does not automatically trust an observed UUID. Set `enabled: true` only after these prerequisites have passed explicit CI acceptance.

Rotate the dedicated client identity by reconciling the Secret and restarting only the physical collector. For CA rotation, temporarily trust both dedicated CAs, replace the leaf certificates and then remove the old CA. Loss of credentials must produce missing/unhealthy evidence and blocked AI admission, never an authentication bypass.

## Capacity decisions

Every filesystem space/inode, project usage and physical data/metadata measurement must be present, healthy, match its configured identity and be at most 90 seconds old. Future timestamps, nonfinite percentages and out-of-range values fail closed. Guest and physical collectors run every 30 seconds; do not refresh upstream timestamps in the collector.

At 80 percent the policy warns. At 90 percent, or with invalid telemetry, it blocks startup/new work and requests graceful drain. A pressure latch clears after five continuous minutes below 80 percent. Interrupted measurement continuity or controller recovery resets that interval. Clearing capacity pressure does not start AI. The controller integration must persist a drain as desired off and alert separately; neither is implemented merely by returning a policy decision.

There is no automatic deletion or force-termination path. Overcommit cannot guarantee enough physical capacity for every admitted operation between measurements. Application emptyDir and ephemeral-storage limits are separate kubelet eviction controls, not synchronous project quota enforcement. Memory-backed emptyDir consumption counts against memory, so any such use needs a separate memory budget.

## Verification and evidence

Local checks are distinct from successful GitHub deployment and live behavior:

- Strict OpenSpec validation passes for the scheduling, homelab and Odysseus active changes.
- Capacity boundary, invalid/stale measurement, hysteresis, Helm/RBAC separation and merge-gate tests run without production credentials.
- The disposable Linux loop-filesystem test proves actual quota write rejection with physical headroom, a successful neighboring write, overcommitted declarations without filling storage, stable project/limit configuration across unmount/remount, and rejection of disabled quotas, missing mounts and incorrect devices.
- A separate adversarial check verifies a file owner inside a user namespace cannot move its file to project zero. The unprotected baseline escape was observed and is recorded above.
- These local Linux tests are not evidence of a worker reboot, actual Pod user-namespace support, independent physical collector connectivity or a production deployment.

The `storage-foundation` reusable CI workflow repeats isolated Linux checks. Selection in the required apply gate includes test-only edits; selected failures, cancellations, missing jobs and unexpected skips fail the gate. Production maintenance and collector enrollment acceptance remain explicitly outstanding. No reset or application migration is invoked by the workflow.

## Data recovery

Project quotas, retained PVs, Git history and OpenTofu state are not application backups. Before the later authorized reset, record exact old claim/PV UIDs and paths, stop and verify all writers, and capture any separately desired application backup using the existing Odysseus backup procedure. The reset record must be durable and single-use, and must name only the three authorized application volumes. This foundation contains no reset code.

Reconstruct quota configuration before restoring data to fresh isolated claims. Restore workspace and vector data with ownership compatible with the user-namespaced Pod, verify representative records and model inventory, and document external credentials separately. Do not mark recovery complete until an isolated restore actually succeeds. Configuration rollback cannot recover data erased by the authorized reset.
