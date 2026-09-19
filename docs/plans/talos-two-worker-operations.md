# Two-worker Talos operations

Status: secondary Kubernetes capacity is active, accepted 2026-09-19.
All three nodes are Ready. Worker-02 passed Talos health, Cilium reachability,
bidirectional Pod/Service/DNS and gVisor stateless placement tests. All 17 PVCs
and 16 PVs retain their baseline identities/bindings, with protected consumers
on worker-01. Temporary acceptance resources have been removed.

The authoritative address register, including the two IMM2 interfaces, is
[the homelab network inventory](../homelab-network-inventory.md). The
secondary physical server and joined `talos-worker-02` are documented there.

Secondary CacheVault CVPM02 reports failed/replacement required. Leave the
controller in write-through mode, disk cache disabled and Cache When BBU Bad
off until repaired. This affects write performance; the array itself reported
optimal with all 16 disks online. This maintenance item is not a completed
repair, nor evidence of full-platform disaster-recovery readiness.

## Target topology

| Location | Guest | VM ID | RAM | Disk | Address |
| --- | --- | ---: | ---: | ---: | --- |
| Primary PVE 10.0.0.224 | talos-cp-01 | 100 | 4 GiB | 100 GiB | 10.0.0.221 |
| Primary PVE 10.0.0.224 | talos-worker-01 | 102 | 112 GiB | 320 GiB OS + 1,200 GiB data | 10.0.0.222 |
| Secondary PVE 10.0.0.223 | talos-worker-02 | 103 | 112 GiB | 320 GiB | 10.0.0.225 |

Ballooning remains disabled. Each 128-GiB PVE host retains 12 GiB or more for
the host. Worker-02 uses the QEMU Guest Agent and gVisor schematic, starts on
boot, and has no local-PVC data disk. 10.0.0.225 is guest-configured static:
do not create a Rogers DHCP reservation. Recheck it is unused immediately before
provisioning. The API VIP is 10.0.0.231; .230 remains occupied.

Worker-02 sets `machine.sysctls.user.max_user_namespaces: "11255"`, required by
the [gVisor extension](https://github.com/siderolabs/extensions/blob/main/container-runtime/gvisor/README.md).
This permits unprivileged user namespaces in place of Talos's hardened zero
default. Keep sandbox admission, runtime selection and resource controls;
installing the extension alone does not prove a gVisor Pod can start.

The current control plane stays a single etcd member for now. Later move
talos-cp-01 to a dedicated always-on third physical machine, retain a
single-member control plane, and first prove etcd snapshot recovery. This is not
HA and the IMM2 burst host must never become the control-plane host.

## Ordered live runbook

The join below has been executed; do not recreate VM 103 or repeat bootstrap.
For reconstruction, restore the existing cluster secrets and private secondary
OpenTofu state first. The accepted generated configuration directory is
`~/.config/aws-account-infra/talos/homelab/three-node-20260919-worker02-final`.
Earlier output without `-final` is historical and must not be used to reinstall.
The original output had a truncated installer digest; the intermediate `-fixed`
output predates the gVisor user-namespace prerequisite. Fresh generation and
strict cross-file validation are required before recovery use.

Repeatable smoke resources are in
`kubernetes/platform/two-worker/worker-join-smoke.yaml`. Verify its namespace
and RuntimeClass names are unused before creating it; exercise Pod IP,
ClusterIP and service DNS in both directions, then delete only those resources.
The temporary RuntimeClass is not a permanent sandbox platform or admission
policy rollout. Run `talosctl health` against the control plane, specifying
`.221` as control-plane and `.222,.225` as workers; query node Ready and CoreDNS
separately because the server-side health check skips those two checks.

1. Verify secondary IMM at .67, primary IMM at .98, and trusted PVE access at
   .223/.224 after boot. Capture installed DIMMs, `free -h`, EDAC/ECC counters,
   hardware event logs, and `qm config` on both hosts. Confirm 128 GiB installed
   per host and budgets of 12 GiB primary / 16 GiB secondary reserve. Missing
   EDAC reporting is not evidence of zero errors.
2. Verify worker-01 has 112 GiB fixed RAM and retains its 320-GiB OS
   and 1,200-GiB data disks. If it is stopped with the old 172-GiB setting after
   the DIMM move, capture its configuration and reduce only memory to 114688
   MiB before starting it. Never resize a running worker. The physical DIMM
   move is operator-performed; do not repeat it. Record
   protected Pi-hole, CNPG/PostgreSQL, Nexus and Nexus PostgreSQL PVC/PV UIDs,
   bindings, consuming Pods and primary placement before creation.
3. Before creation, verify the secondary PVE node name and supply it as
   node_name; set its PROXMOX_VE_ENDPOINT to
   https://10.0.0.223:8006/api2/json outside Git. Run the secondary OpenTofu
   plan after verifying storage health, pinned ISO and VM ID 103 vacancy.
   Immediately before creation, check .225 against router reservations and
   same-LAN ARP probes; a failed ping alone does not establish vacancy. Accept
   only a plan creating VM 103 with one 320-GiB OS disk, then apply that plan.
4. Use the three-node configuration generated from the existing secrets bundle.
   Verify its credentials against the existing control plane. In maintenance
   mode confirm worker-02's MAC, identity and sole OS disk `/dev/sda` before
   applying only `talos-worker-02.machineconfig.yaml`. Do not reapply bootstrap
   configurations to the existing primary nodes or run etcd bootstrap again.
5. Verify three unique node identities/IPs, worker-02 `Ready`, Talos health,
   38 vCPUs / expected memory, QEMU agent/gVisor and VIP .231 continuity.
   Verify `homelab.tfdraw.dev/worker-role=secondary` and
   `homelab.tfdraw.dev/stateless-compute=true`, with no storage label. Run
   Cilium cross-node pod-to-pod and Service connectivity checks and a temporary
   stateless Pod selected onto worker-02; remove the test resources afterward.
6. Compare protected PVC/PV UIDs and bindings with the preflight inventory;
   verify consuming Pods and PV affinity remain primary-pinned. Confirm no new
   PVC, local PV, secondary StorageClass or Nexus cache workload exists on
   worker-02. Update the inventory and audit log to active only after all live
   acceptance checks pass. Kueue and AI retirement are separate operations.

## Deferred secondary cache

The 200-GiB secondary Nexus OCI cache disk, Nexus cache instance, Docker Hub/ECR
proxying, registry mirrors, Roles Anywhere credential refresher and
`cache-registry.homelab.tfdraw.dev` are explicitly deferred. Worker-02 has only
its OS disk and no local-storage label or StorageClass. Existing Nexus and
Nexus PostgreSQL remain protected primary-local workloads. Worker-01's
1,200-GiB data disk remains primary-local storage; it was not superseded by
the memory or two-worker revision.

## AI retirement, deliberately irreversible

Before removing anything, record the protected PVC names and owners for Pi-hole,
CNPG/PostgreSQL, Nexus, and Nexus PostgreSQL. Do not select those namespaces,
Helm releases, PVs, or claims in any delete command.

Then remove GitOps/Helm ownership and workloads for ai-runtime, Ollama,
ChromaDB, Odysseus, and SearxNG; delete their namespaces; and delete their PVCs
and retained PV data. Do not take a recovery copy. Finish with cluster-wide
checks proving no matching workload, PVC, or PV remains, while all protected
claims remain bound and primary-pinned. This repository has no tracked AI
manifests, so the exact release and namespace names must be obtained from the
live cluster before deletion.

## Future IMM2 controller boundary

Do not deploy an IMM2 capacity controller yet. Its eventual controller runs on
always-on infrastructure with a least-privilege BMC account. It advertises
secondary Kueue capacity only after the node is Ready; before power-off it
cordons, drains, and removes capacity. It refuses shutdown while admitted work,
Pods, or local storage remain, and has cooldowns plus a manual kill switch.
