# Proxmox Kubernetes worker plan

Status: **proposed; hardware discovery and implementation pending**

This plan adds the newly acquired 192 GiB Proxmox server to the existing
`homelab` kubeadm cluster as its first worker. The existing `ubuntu_desktop`
remains the single control plane and etcd member.

The Facebook Marketplace listing does not expose the server's CPU, disk, RAID,
or NIC details to unauthenticated clients. CPU topology, disk layout, and final
VM sizing therefore remain provisional until hardware discovery is complete.

## Decision

Keep Proxmox VE on the physical server and run Kubernetes inside one substantial
Ubuntu virtual machine.

Do not:

- install kubeadm directly on the Proxmox host;
- run the Kubernetes node in an LXC container;
- split the server into multiple worker VMs and treat them as independent
  availability domains; or
- add a second control-plane member without a three-member, physically
  independent control-plane design.

A VM provides a clean kernel and operating-system boundary, predictable Ansible
behavior, straightforward rebuilds, and room for the physical server to host
other workloads later. Multiple VMs on the same chassis can provide workload
separation, but they do not provide hardware fault tolerance.

## Existing cluster constraints

The repository currently defines:

- `ubuntu_desktop` as the only member of `kubernetes_control_plane`;
- no hosts in `kubernetes_workers`;
- kubeadm and kubelet version `v1.35.7`;
- Ubuntu 26.04 as a hard preflight requirement;
- containerd as the container runtime;
- Cilium using VXLAN tunnel mode;
- MetalLB using `10.0.0.231-10.0.0.253`;
- the Kubernetes API at `10.0.0.156:6443`; and
- local-path volumes under `/var/local-path-provisioner` on nodes labeled
  `storage=local`.

Adding this worker increases compute capacity. It does not make the Kubernetes
API or etcd highly available. Loss of `ubuntu_desktop` will still make the
control plane unavailable.

## Phase 1: inspect and burn in the server

Before allocating workloads, update the server's BIOS, management-controller,
RAID-controller, drive, and NIC firmware where supported. Record the current
configuration before changing it.

Collect the following from the Proxmox shell:

```bash
lscpu
free -h
lsblk -o NAME,SIZE,TYPE,MODEL,SERIAL
ip -br link
pvesm status
```

Also confirm:

- whether the system is single-socket or dual-socket;
- physical cores, threads, and NUMA nodes;
- that all 192 GiB is ECC memory and reports no corrected or uncorrected errors;
- drive media, capacity, endurance, SMART health, and controller mode;
- whether Proxmox storage uses ZFS, hardware RAID, LVM-thin, or another backend;
- NIC link speed and which interface backs `vmbr0`;
- redundant power-supply health, if present; and
- UPS capacity and clean shutdown behavior.

Run a complete memory test and a storage burn-in appropriate to the installed
media before treating the machine as reliable. Do not run destructive disk tests
until the exact test targets and any existing data have been reviewed.

Exit criterion: firmware is current, memory is clean, storage is healthy, and
the physical network configuration is documented.

## Phase 2: create the worker VM

Use the following initial configuration. Adjust CPU topology and disks after the
hardware inspection.

| Setting | Initial value |
| --- | --- |
| Name | `k8s-worker-pve01` |
| Guest OS | Ubuntu Server 26.04 |
| Machine type | q35 |
| Firmware | UEFI/OVMF |
| RAM | 128 GiB fixed |
| CPU | Approximately 75 to 80 percent of physical cores |
| CPU type | `host` |
| Network | VirtIO NIC bridged to `vmbr0` |
| OS disk | 80 to 100 GiB |
| Container disk | 250 to 500 GiB |
| Optional local-PV disk | Sized from workload and backup requirements |
| Disk controller | VirtIO SCSI Single |
| QEMU guest agent | Enabled |
| Automatic startup | Enabled after Proxmox networking |

Leave approximately 64 GiB unassigned initially for Proxmox, filesystem cache,
and future VMs. Increase the worker after observing real use rather than assigning
all physical memory on day one.

Do not overcommit CPU for the Kubernetes worker. If the host is dual-socket and
the VM spans NUMA nodes, review Proxmox NUMA configuration after recording the
exact processor model and topology.

Install and enable the QEMU guest agent in Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y qemu-guest-agent
sudo systemctl enable --now qemu-guest-agent
```

Disable memory ballooning initially so kubelet sees stable capacity. Use VirtIO
SCSI Single with an I/O thread. Enable discard only when the underlying storage
supports thin provisioning, and enable periodic trimming in the guest when
discard is in use.

If Proxmox uses ZFS, use ext4 or XFS inside the guest rather than nesting ZFS.
Proxmox snapshots and backups are useful for VM recovery, but they are not a
substitute for application-consistent persistent-volume backups.

## Phase 3: configure networking

Attach the VM directly to the LAN through `vmbr0`; do not put it behind Proxmox
NAT. Reserve a stable `10.0.0.0/24` address in DHCP outside the MetalLB pool
`10.0.0.231-10.0.0.253`.

Keep MTU 1500 unless every physical switch, interface, bridge, and cluster node
has already been validated with the same jumbo-frame MTU.

Allow the following traffic between cluster nodes:

| Protocol and port | Purpose |
| --- | --- |
| TCP 6443 | Worker to Kubernetes API at `10.0.0.156` |
| TCP 10250 | Kubelet API between the control plane and worker |
| UDP 8472 | Cilium VXLAN between nodes |
| TCP 4240 | Cilium health checks between nodes |
| ICMP | Cilium node health checks |
| TCP/UDP 30000-32767 | NodePort, only if directly consumed |

Before joining, verify bidirectional LAN reachability and at minimum test the API
and Cilium paths:

```bash
ping -c 3 10.0.0.156
nc -zv 10.0.0.156 6443
```

## Phase 4: prepare Ubuntu

During Ubuntu installation:

- set the hostname to `k8s-worker-pve01`;
- create an administrative user reachable with an SSH key;
- do not enable password-only remote administration;
- keep the default route on the bridged LAN interface;
- install no alternative Kubernetes distribution or container runtime; and
- ensure time synchronization is active.

Verify that the VM has unique identity values before joining:

```bash
hostnamectl hostname
ip link
sudo cat /sys/class/dmi/id/product_uuid
```

Kubernetes requires a unique hostname, MAC address, and product UUID for each
node. Do not clone this VM into another Kubernetes node without regenerating all
three values.

## Phase 5: add the Ansible inventory entry

Add the host to
`ansible/inventories/local/hosts.yml` under `ubuntu_compute`,
`kubernetes_nodes`, and `kubernetes_workers`:

```yaml
all:
  children:
    ubuntu_compute:
      hosts:
        k8s_worker_pve01:
          ansible_host: 10.0.0.X
          ansible_user: tushar
          # Use standard sudo unless the new VM has the local sudo.ws wrapper.
          ansible_become_exe: /usr/bin/sudo

    kubernetes_nodes:
      hosts:
        ubuntu_desktop:
        k8s_worker_pve01:

    kubernetes_control_plane:
      hosts:
        ubuntu_desktop:

    kubernetes_workers:
      hosts:
        k8s_worker_pve01:
```

Replace `10.0.0.X` with the reserved LAN address. Preserve all existing inventory
groups and host settings. Do not add this host to `nvidia_gpu_nodes`,
`legacy_nodes`, or `kubernetes_control_plane` unless the hardware and cluster
architecture change deliberately.

Validate inventory resolution:

```bash
make -C ansible check
```

## Phase 6: prepare and join the node

Run check mode first and review every proposed change:

```bash
ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg" \
  ansible-playbook ansible/playbooks/node-prepare.yml \
  --limit k8s_worker_pve01 --check --diff
```

Apply node preparation only after the preview is accepted:

```bash
ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg" \
  ansible-playbook ansible/playbooks/node-prepare.yml \
  --limit k8s_worker_pve01
```

Join the worker:

```bash
ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg" \
  ansible-playbook ansible/playbooks/workers.yml
```

The worker playbook generates a short-lived 15-minute kubeadm token on the
control plane, suppresses it from logs, and joins uninitialized workers through
containerd.

## Phase 7: validate

Run the repository validation and inspect node state:

```bash
make -C ansible validate
kubectl get nodes -o wide
kubectl describe node k8s-worker-pve01
kubectl top nodes
```

Confirm that:

- both nodes report `Ready`;
- the worker advertises its reserved LAN address;
- allocatable CPU and memory match the expected VM reservation;
- Cilium is healthy on both nodes;
- cross-node pod traffic works;
- the worker returns after a controlled VM reboot; and
- draining and uncordoning the worker works before real workloads depend on it.

Re-run the node-preparation playbook and require no unexpected changes.

## Scheduling and storage policy

Initially use this worker for stateless and memory-intensive workloads. Do not
label it `storage=local` during the first join.

The current add-on automation applies `storage=local` only to the control-plane
node, and the local-path provisioner selects that label. Therefore, existing
local-path workloads remain on `ubuntu_desktop` after this worker joins.

Before enabling persistent volumes on the worker:

1. provision and mount a dedicated filesystem at
   `/var/local-path-provisioner`;
2. define the worker's storage label through Ansible-managed configuration;
3. document application-level backups and restore tests;
4. decide which workloads may tolerate the loss of this physical server; and
5. migrate existing volumes explicitly rather than expecting Kubernetes to move
   node-local data.

Do not treat a Proxmox VM snapshot as the sole backup for application data.

## Availability warning

This design retains one control plane and one worker across two physical hosts.
It improves workload capacity and allows some running worker workloads to survive
a control-plane outage temporarily, but scheduling and cluster administration
still stop if `ubuntu_desktop` or its etcd data is unavailable.

Do not create a two-member etcd cluster. A two-member cluster requires both
members for quorum and tolerates no member failure. Proper control-plane HA needs
three control-plane members placed on independent physical failure domains, plus
a stable API endpoint.

## Acceptance criteria

- Hardware health and topology are documented.
- The Proxmox host retains sufficient CPU, memory, and storage headroom.
- The Ubuntu 26.04 VM has a stable LAN address and unique identity.
- Ansible check mode has been reviewed before apply.
- `k8s-worker-pve01` joins at the repository-pinned Kubernetes version.
- Both nodes remain Ready after sequential reboots.
- Cilium health and cross-node networking tests pass.
- No bootstrap token, kubeconfig, private key, or other secret enters source
  control or command output.
- Persistent storage remains on the existing labeled node until a separate
  storage migration is approved.

## References

- [Installing kubeadm](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/install-kubeadm/)
- [Kubernetes ports and protocols](https://kubernetes.io/docs/reference/networking/ports-and-protocols/)
- [Cilium system requirements](https://docs.cilium.io/en/stable/operations/system_requirements/)
- [Proxmox VE administration guide](https://pve.proxmox.com/pve-docs/pve-admin-guide.pdf)
- [Repository Kubernetes plan](./kubernetes.md)
- [Repository Ansible guide](../../ansible/README.md)
