# Talos-Based Kubernetes Rebuild Plan

## Summary and recommendation

Keep Proxmox as the bare-metal operating system and rebuild the Kubernetes
cluster using Talos Linux virtual machines.

Recommended baseline:

- Proxmox VE remains installed directly on the IBM System x3550 M4.
- Talos Linux v1.13.9 runs the Kubernetes control plane and CPU workers as
  Proxmox VMs.
- Kubernetes is pinned initially to v1.36.3.
- The existing Ubuntu 26.04 desktop remains a conventional GPU worker.
- Mixed or untrusted workloads run on a separate Talos VM through gVisor.
- A separate Debian NAS VM serves general storage and brokered Kubernetes
  workspaces; the NAS is not part of the Kubernetes cluster.
- Backups go to a dedicated encrypted AWS S3 bucket.
- No USB installer is needed. Upload the Talos ISO to Proxmox and boot the VMs
  from it.

Talos wins for this clean-slate cluster because it is Kubernetes-only,
immutable, API-managed, and has no SSH server or general package manager.
Ubuntu remains the better choice for the GPU machine because NVIDIA tooling
and conventional troubleshooting are substantially easier there. Talos v1.13
supports Kubernetes 1.31 through 1.36 and documents Proxmox as a supported
installation target. See the [Talos support
matrix](https://docs.siderolabs.com/talos/v1.13/getting-started/support-matrix)
and [Talos Proxmox
installation](https://docs.siderolabs.com/talos/v1.13/platform-specific-installations/virtualized-platforms/proxmox).

### Hardware-specific findings

The Proxmox inspection found:

- IBM System x3550 M4, BIOS 3.20 from June 2020.
- Two Xeon E5-2695 v2 processors.
- 24 physical cores, 48 threads, and two NUMA nodes.
- 188 GiB usable registered ECC memory.
- Four Intel I350 1 GbE ports and two currently disconnected Emulex 10 GbE
  ports.
- Eight approximately 52,000-hour-old 300 GB 15K SAS disks behind an IBM
  ServeRAID M5110.
- A roughly 1.9 TiB logical disk, likely RAID5 based on capacity, although the
  RAID level could not be directly queried.
- Several drives report grown defects, with one reporting seven.
- The LVM-thin backing device does not support discard.
- No existing Proxmox VMs or containers.

The old RAID is the dominant reliability risk. It is acceptable as a working
store only because all important state will be recoverable from S3.

### Weighted distribution comparison

Scores are weighted for this use case: Kubernetes specialization and attack
surface 25%, lifecycle and update safety 20%, hardware compatibility 15%,
isolation and recovery 15%, ecosystem 15%, and migration effort 10%.

| Distribution | Score | Finding |
|---|---:|---|
| Talos Linux | 8.9/10 | Best clean-slate Kubernetes appliance and best fit for isolated trusted and sandbox VMs |
| Ubuntu Server 26.04 LTS | 8.2/10 | Best conventional Linux option and the selected GPU-worker OS |
| Flatcar Container Linux | 7.6/10 | Strong immutable design, but kubeadm, extensions, and diagnostics require more assembly than Talos |
| Debian 13 | 7.5/10 | Stable and lean, but offers little practical advantage over Ubuntu for this cluster |
| Rocky Linux 9 | 7.0/10 | Compatible, but its operational ecosystem is less aligned with the existing automation |
| Fedora Server 44 | 6.2/10 | Excellent current software, but its approximately 13-month lifecycle creates unnecessary node churn |
| Rocky Linux 10 | Disqualified | Requires x86-64-v3; the Ivy Bridge CPUs lack required AVX2, BMI2, and FMA support |

Ubuntu 26.04 receives standard security maintenance through 2031. Use the
standard amd64 server image, not an `amd64v3` cloud image. See the [Ubuntu
26.04 release notes](https://documentation.ubuntu.com/release-notes/26.04/)
and [Ubuntu architecture
levels](https://documentation.ubuntu.com/project/how-ubuntu-is-made/concepts/supported-architectures/).

Debian 13 receives full support through August 2028 and LTS through June 2030.
See the [Debian 13 release
information](https://www.debian.org/releases/trixie/).

Fedora's short lifecycle is poorly matched to a homelab node expected to run
unattended for long periods. See the [Fedora release life
cycle](https://fedoraproject.org/wiki/Fedora_Release_Life_Cycle/zh-cn).

Rocky 10's x86-64-v3 requirement makes it unsuitable for these CPUs. See the
[Rocky Linux 10 release
notes](https://docs.rockylinux.org/latest/releases/release_notes/10_0/).

## Target architecture

### Proxmox host

Before creating the cluster:

- Update the IBM BIOS, ServeRAID firmware, NIC firmware, and Proxmox packages
  to stable supported versions.
- Export the Proxmox network and storage configuration.
- Confirm the actual RAID level, cache-protection status, patrol-read status,
  and individual drive health using an appropriate MegaRAID or StorCLI
  utility.
- Enable VT-x, VT-d/IOMMU, ECC reporting, and hardware virtualization.
- Disable Hyper-Threading/SMT because mixed or untrusted workloads will run on
  an Ivy Bridge host with SMT-sensitive speculative-execution exposure.
- Keep the existing `vmbr0` 1 GbE network for the first deployment.
- Do not enable virtual-disk discard.
- Reserve a fixed Kubernetes API address outside `10.0.0.231-253`, which
  remains the MetalLB pool.
- Protect Proxmox management access with the trusted LAN and Tailscale only.

### VM allocation

| VM | Purpose | vCPU | Memory | Disk | Placement |
|---|---|---:|---:|---:|---|
| `talos-cp-01` | Control plane and etcd | 2 | 4 GiB | 100 GiB | Trusted only, no application workloads |
| `talos-worker-01` | Trusted CPU workloads | 8 | 64 GiB | 200 GiB | Trusted workloads and system add-ons |
| `talos-sandbox-01` | Mixed or untrusted workloads | 10 | 80 GiB | 200 GiB | gVisor-only application namespaces |
| `agent-nas-01` | General NAS and Kubernetes workspace storage | 2 | 8 GiB | 32 GiB OS plus 1 TiB data | Outside Kubernetes; trusted infrastructure |

This assigns 22 vCPUs and 156 GiB of the server's 24 physical cores and 188 GiB
usable RAM. Memory remains fixed, leaving 32 GiB unassigned for Proxmox,
filesystem cache, and recovery work. Configure the NAS with two visible vCPUs
but an aggregate CPU limit equivalent to one physical core and a lower CPU
weight than the control plane. With all guests CPU-bound, that policy leaves
approximately three cores of host scheduling capacity.

The vCPU counts are configurable Proxmox scheduling limits rather than permanent
hardware partitions. Resize them during a planned VM shutdown as measurements
change. Keep memory ballooning disabled so kubelet sees stable capacity. The
control plane starts at Talos's documented minimum core count with its
recommended 4 GiB memory allocation. This is intentionally below the four-core
production recommendation for a small cluster. One core is below the documented
minimum. Increase control-plane resources if API, etcd, CPU, or memory metrics
demonstrate pressure. See the [Talos system
requirements](https://docs.siderolabs.com/talos/v1.13/getting-started/system-requirements).

The virtual disks total approximately 1,556 GiB of the last-observed 1.75 TiB
thin pool and leave about 236 GiB unallocated. Reconfirm physical and thin-pool
capacity before creating the NAS data disk.

After disabling SMT, keep the control-plane and trusted-worker VM CPUs within
one NUMA locality where practical and the sandbox worker within the other. Do
not exclusively pin every physical core: Proxmox and the NAS need scheduling
headroom for I/O. Derive exact CPU affinity and memory locality from `lscpu -e`
after the BIOS change, then validate them under concurrent compute and storage
load.

All Talos VMs use:

- OVMF/UEFI.
- Q35 machine type.
- CPU type `host`.
- VirtIO network on `vmbr0`.
- VirtIO SCSI, not VirtIO SCSI Single.
- Raw disks on LVM-thin.
- Memory ballooning disabled.
- Memory hotplug disabled.
- Discard disabled.

Use the VM startup order: control plane, NAS, trusted worker, then sandbox
worker.

Multiple control-plane VMs on this one physical server would create false high
availability. Use one control plane until another independent physical machine
is available.

### Kubernetes platform

Pin the initial deployment to:

- Talos Linux v1.13.9.
- Kubernetes v1.36.3.
- Cilium v1.20.1.
- Cilium VXLAN mode.
- Kubernetes kube-proxy retained.
- Cilium `kubeProxyReplacement=false`.

Keeping kube-proxy matches the current cluster and reduces risk with the
existing Istio deployment. Cilium 1.20 supports Kubernetes 1.33 through 1.36.
See [Cilium Kubernetes
compatibility](https://docs.cilium.io/en/stable/network/kubernetes/compatibility/)
and [Cilium and Istio
guidance](https://docs.cilium.io/en/stable/network/servicemesh/istio/).

Talos machine configuration will:

- Set the CNI to `none` so Cilium can be installed after bootstrap.
- Use a stable API IP and certificate SAN.
- Pin installer and system-extension image digests.
- Install the QEMU guest-agent extension.
- Install the gVisor extension only on `talos-sandbox-01`.
- Create a user volume mounted at `/var/mnt/local-path-provisioner`.
- Keep KubeSpan disabled because an external Ubuntu worker will participate.

### Trusted and untrusted scheduling

Create explicit scheduling boundaries:

- Control plane taint: `node-role.kubernetes.io/control-plane:NoSchedule`.
- Sandbox label: `workload.security/sandbox=true`.
- Sandbox taint: `workload.security/sandbox=true:NoSchedule`.
- Trusted-worker label: `workload.security/trusted=true`.
- gVisor `RuntimeClass` using the Talos `runsc` runtime.
- Dedicated sandbox namespaces with Pod Security Admission `restricted`.
- Kyverno policy requiring the gVisor RuntimeClass and sandbox-node selector in
  sandbox namespaces.
- Deny privileged containers, host networking, host PID/IPC, unsafe
  capabilities, and arbitrary host paths in sandbox namespaces.
- Default-deny Cilium ingress and egress policies, followed by explicit
  workload-specific allowances.
- Resource quotas and limits for every sandbox namespace.

gVisor reduces kernel attack surface but does not protect against CPU
side-channel attacks, which is why SMT is disabled and the workloads are
separated into their own VM. See the [gVisor security
model](https://gvisor.dev/docs/architecture_guide/security/) and [Kubernetes
RuntimeClass](https://kubernetes.io/docs/concepts/containers/runtime-class/).

## Repository and interface changes

Replace the current Ubuntu-only cluster assumptions with two explicit
management paths:

- Talos machine configuration and cluster lifecycle for the Proxmox VMs.
- Ansible-managed Ubuntu lifecycle for the external GPU worker.

Add declarative inputs for:

- Talos and Kubernetes versions.
- API IP and DNS SAN.
- Node roles, addresses, taints, labels, CPU, memory, and disk sizes.
- Cilium and MetalLB configuration.
- Talos extension images and immutable digests.
- Sandbox RuntimeClass and admission-policy settings.
- S3 backup bucket, prefix, retention, AWS region, and Roles Anywhere identity.
- Ubuntu external-worker join configuration.

Retire Ubuntu-specific kubeadm control-plane provisioning after the new cluster
is accepted. Preserve the reusable Ubuntu baseline, containerd, NVIDIA, and
worker configuration for the GPU desktop.

Implement a dedicated Ubuntu external-worker role that:

1. Installs the Kubernetes 1.36.3 kubelet and compatible containerd packages.
2. Obtains a short-lived bootstrap token from the Talos-managed control plane.
3. Performs kubelet TLS bootstrap.
4. Waits for certificate approval and confirms the node becomes Ready.
5. Applies GPU labels and taints only after NVIDIA device-plugin validation.

Test this procedure against a disposable Ubuntu VM before touching the GPU
desktop. If standard kubeadm bootstrap cannot complete, use the documented
kubelet TLS-bootstrap configuration directly rather than changing the Talos
control plane.

## AWS identity and backup design

Create a dedicated OpenTofu-managed AWS S3 backup bucket using the repository's
existing encrypted-bucket patterns:

- Bucket versioning enabled.
- S3 Block Public Access fully enabled.
- TLS-only bucket policy.
- Server-side encryption enabled.
- Object Lock enabled at bucket creation.
- Governance retention of 30 days.
- Normal backup retention of 90 days.
- Monthly recovery points retained for one year.
- Separate prefixes for etcd, Kubernetes resources, and application data.
- A dedicated IAM role limited to that bucket and those prefixes.
- Authentication through the existing IAM Roles Anywhere trust model, with no
  long-lived AWS access keys.

Backups consist of three independent layers:

1. Talos etcd snapshots.
2. Declarative cluster configuration and Kubernetes resource backups.
3. Application-consistent backups for every persistent workload.

Run the initial backup uploader from the trusted Ubuntu worker, where the
existing `aws_signing_helper` flow can be retained. Do not make successful
Talos-side ECR or backup identity a prerequisite for bootstrapping the cluster.

A subsequent Talos identity workstream will build and pin a custom system
extension around the official ECR credential-provider and
`aws_signing_helper`. It must generate private keys locally, provision only
signed certificates, and never place private keys or credential values in Git,
logs, command arguments, or Talos machine configuration. Any implementation
involving live certificates or credentials must first load and follow the
repository's `aws-secrets-manager` instructions.

The ECR extension must pass a disposable-node proof before private ECR
workloads move from the Ubuntu worker to Talos.

## Migration sequence

### 1. Hardware safety gate

- Confirm RAID level and cache protection.
- Run full SMART and ServeRAID health checks.
- Configure alerts for media errors, predictive failures, temperatures, ECC
  events, and RAID degradation.
- Do not begin migration if the array is degraded or cache protection has
  failed.

### 2. Current-cluster inventory gate

- Restore access to the current Kubernetes API.
- Inventory namespaces, Helm releases, CRDs, PVCs, storage paths, Services,
  ingresses, certificates, and GPU workloads.
- Take an etcd snapshot and application-level backups.
- Restore those backups in a disposable environment before destructive work.

### 3. Proxmox preparation

- Disable SMT and validate 24 visible physical CPUs.
- Create the three VMs.
- Upload the Talos ISO to Proxmox and boot from it.
- Apply CPU, memory, disk, NUMA, and startup settings.

### 4. Parallel Talos bootstrap

- Generate fresh Talos PKI and machine configurations.
- Bootstrap `talos-cp-01`.
- Install Cilium and verify core DNS and networking.
- Add the trusted worker, followed by the sandbox worker.
- Install MetalLB, cert-manager, Istio, Kyverno, storage provisioner,
  monitoring, and backup components.

### 5. Compatibility proofs

- Join a disposable Ubuntu VM as an external worker.
- Validate gVisor scheduling and isolation.
- Validate Istio sidecars and service traffic with Cilium.
- Validate local-volume creation and recovery.
- Complete an S3 backup and restore.
- Prove private ECR pulls on Ubuntu before attempting the Talos extension.

### 6. Workload migration

- Redeploy applications from Helmfile and Git-managed manifests.
- Restore application data rather than copying raw local-path directories
  blindly.
- Move trusted workloads first.
- Move explicitly sandboxed workloads only after admission-policy tests pass.
- Join the real Ubuntu GPU desktop last and validate NVIDIA workloads.

### 7. Cutover

- Freeze writes on the old cluster.
- Take final etcd and application backups.
- Restore final data into the Talos cluster.
- Move DNS and service consumers to the new ingress and MetalLB addresses.
- Observe for at least 24 hours before removing the old control-plane state.

## Acceptance tests

The rebuild is complete only when:

- Proxmox reports 24 physical CPUs with SMT disabled and no ECC errors.
- RAID monitoring can identify every physical disk and alert on degradation.
- All three Talos VMs survive orderly reboot and return Ready automatically.
- Loss and recreation of a worker VM does not require manual cluster repair.
- The control-plane VM runs no ordinary workloads.
- A normal pod cannot schedule onto the sandbox node.
- A sandbox pod cannot run without gVisor.
- Privileged, host-network, host-PID, and unauthorized hostPath pods are
  rejected in sandbox namespaces.
- Cilium network-policy tests prove default-deny and required allow paths.
- Istio ingress and sidecar traffic operate correctly.
- The Ubuntu GPU worker joins, reboots, and returns Ready.
- An NVIDIA test pod sees the GPU only on the Ubuntu worker.
- Public and private container-image pulls succeed using short-lived
  credentials.
- An etcd snapshot is restored into a disposable Talos control plane.
- At least one stateful application is backed up to S3 and restored from
  scratch.
- Deleting a recent S3 backup object does not bypass versioning or Object Lock
  retention.
- Rebuilding the entire Kubernetes cluster from Git, Talos configuration, and
  S3 backups is documented and rehearsed.

## Assumptions and defaults

- Proxmox remains the bare-metal layer because it provides useful VM isolation
  for mixed-trust workloads.
- The present RAID is retained temporarily, despite its age.
- AWS S3 is the selected off-host recovery destination.
- The first deployment remains on 1 GbE; the Emulex 10 GbE adapters are a later,
  independently tested upgrade.
- The cluster is not physically highly available while its control plane
  resides on one Proxmox server.
- Local-path storage is treated as working storage, not as a backup.
- The Ubuntu GPU desktop remains a separate physical Kubernetes worker.
- Fresh Talos PKI and a parallel rebuild are preferred over trying to convert
  the existing kubeadm control plane in place.
