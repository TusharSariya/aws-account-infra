# Local Kubernetes implementation plan

Status: **proposal only — do not implement from this document without a separate review**

This plan describes a full upstream Kubernetes cluster on two physical Ubuntu hosts.
The Mac is the administration workstation and may run separate Linux containers through
OrbStack or Apple container tooling, but it is not a native Kubernetes node. Kubernetes
node components require Linux, and the cluster must remain available when the laptop is
offline.

## Proposed architecture

- Ubuntu host 1: kubeadm control plane, etcd, and schedulable worker.
- Ubuntu host 2: kubeadm worker.
- Mac: Ansible, `kubectl`, Helm, and Helmfile client.
- Runtime: containerd on both Ubuntu hosts.
- Pod networking and policy: Cilium.
- LAN service addresses: MetalLB in layer-2 mode.
- HTTP routing: ingress-nginx behind a MetalLB address.
- Default persistent volumes: Local Path Provisioner.

This is not highly available. Losing host 1 stops the Kubernetes API and scheduling,
although already-running workloads on host 2 may continue temporarily. Do not treat the
cluster as durable storage or production infrastructure.

## Decisions required before implementation

Record these values in a reviewed cluster configuration before writing automation:

- Stable LAN address and hostname for each Ubuntu host.
- A control-plane API address that will not change.
- The router's DHCP range and an unused contiguous address range for MetalLB.
- Pod and service CIDRs that do not overlap the LAN, VPN, Docker, OrbStack, or future
  cloud networks.
- DNS names for the API and ingress endpoint, plus how local DNS will resolve them.
- Whether host 1 has enough CPU and memory to run control-plane and workload pods.
- Which workloads need persistence and whether node-local data loss is acceptable.
- A maintenance window and the expected cluster availability when either host is off.

Suggested minimum capacity is 4 CPU cores, 8 GiB RAM, and 50 GiB free storage per host,
but actual sizing must follow the intended jobs. Both hosts need synchronized clocks,
stable wired networking where possible, unique hostnames/MAC addresses, and passwordless
SSH keys for administration. Swap and firewall requirements must be reviewed against the
selected Kubernetes and Cilium versions rather than changed blindly.

## Ownership boundaries

- Ansible owns Linux prerequisites, package repositories, kernel modules/sysctls,
  containerd, kubeadm packages, kubelet service configuration, and idempotent node
  initialization/join operations.
- kubeadm owns control-plane certificates, static pods, bootstrap tokens, and node joins.
- Helmfile owns Cilium, MetalLB, ingress-nginx, Local Path Provisioner, and later shared
  platform add-ons.
- Workload repositories own application namespaces, releases, policies, and application
  data lifecycle.
- This infrastructure repository stores no unencrypted join tokens, kubeconfigs, private
  keys, or application secrets.

## Implementation phases

### 1. Discovery and preflight

1. Capture OS releases, kernel versions, CPU architecture, resources, disks, NICs,
   default routes, DNS, and current container runtimes from both hosts.
2. Confirm the hosts can communicate bidirectionally on the ports required by the
   selected Kubernetes/Cilium release.
3. Select a currently supported Kubernetes minor release and pin kubeadm, kubelet,
   kubectl, containerd, Cilium, Helm chart, and Helmfile versions as one compatibility
   set. Verify choices against primary project documentation at implementation time.
4. Record the required network values above and test that the MetalLB range is unused.
5. Produce an Ansible `--check --diff` preview. No kernel, firewall, runtime, or package
   repository changes proceed until this output is reviewed.

Exit criterion: a signed-off inventory and compatibility matrix with no address overlap.

### 2. Linux and runtime preparation

1. Add dedicated Ansible roles for Kubernetes prerequisites and containerd; do not fold
   these into the general compute baseline.
2. Configure required kernel modules, sysctls, cgroup driver, package repositories, and
   pinned packages using handlers for controlled restarts.
3. Validate containerd independently on both hosts and confirm reboot persistence.
4. Reboot one host at a time if required, proving SSH recovery before continuing.

Rollback: remove Kubernetes repositories/packages and restore captured containerd,
sysctl, module, and firewall configuration. Preserve logs for diagnosis.

### 3. Control plane and worker

1. Render a reviewed kubeadm configuration file; do not construct a long command from
   shell variables.
2. Initialize host 1 and immediately copy the administrator kubeconfig to an encrypted
   local location on the Mac with least-privilege file permissions.
3. Install Cilium before expecting nodes to become Ready.
4. Create a short-lived join command, join host 2, and revoke/expire the token afterward.
5. Intentionally remove the control-plane scheduling taint only after confirming host 1
   has sufficient capacity.

Exit criterion: both nodes are Ready after a reboot, system pods are healthy, and no
bootstrap credential remains in logs or source control.

### 4. Cluster services

1. Add a cluster-scoped Helmfile with pinned releases and environment-specific values.
2. Verify Cilium connectivity and network-policy tests before other add-ons.
3. Install MetalLB with the reviewed LAN pool; confirm an assigned address is reachable
   from the Mac and does not conflict with DHCP.
4. Install ingress-nginx and route a disposable HTTP service through local DNS.
5. Install Local Path Provisioner, create a test PVC, restart its pod, and document the
   node-affinity and data-loss behavior.

Rollback each add-on independently through Helmfile. Removing Local Path Provisioner
must never imply deleting retained workload data automatically.

### 5. Operations and recovery

Document and rehearse:

- Adding, draining, upgrading, and removing a worker.
- Sequential minor-version upgrades; never skip unsupported versions.
- Renewing and inspecting control-plane certificates.
- Encrypted etcd snapshots copied off host 1, with a tested restore procedure.
- Rebuilding the cluster from Ansible plus Helmfile and restoring only explicitly
  supported workload data.
- Node disk failure, control-plane loss, expired kubeconfig, CNI failure, and accidental
  MetalLB address conflict.
- Resource requests/limits and a policy preventing jobs from exhausting host 1.

## Security requirements

- Use SSH keys and retain host-key checking; do not put SSH passwords in inventory.
- Encrypt kubeconfigs, backup credentials, and other secrets with Ansible Vault or SOPS.
- Restrict the Kubernetes API to trusted LAN/VPN sources.
- Start with default-deny workload network policies once DNS and required egress are
  understood.
- Do not expose the dashboard or unauthenticated administrative services.
- Run security and image scanning before admitting third-party workloads.
- Back up etcd and application data separately; an etcd snapshot does not contain
  persistent-volume contents.

## Acceptance tests

- Re-running Ansible produces no unexpected changes.
- Both hosts return Ready after sequential reboots.
- Cilium health and cross-node connectivity tests pass.
- A denied pod-to-pod connection proves network policy enforcement.
- MetalLB exposes a service on the LAN without address conflicts.
- ingress-nginx routes a test hostname from the Mac.
- A PVC binds, survives a pod restart on its original node, and demonstrates documented
  failure when that node is unavailable.
- A scheduled job runs on each Ubuntu host under explicit resource limits.
- An etcd snapshot is restored in a disposable recovery exercise before backups are
  considered operational.

## Explicitly deferred

- Running a Kubernetes node directly on macOS.
- A control-plane VM hosted on the laptop.
- Highly available control planes or external etcd.
- Distributed storage, automatic failover, public internet exposure, and cloud nodes.
- Application deployment design.
