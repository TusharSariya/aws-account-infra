# Homelab network inventory

Status: current intended allocation, reconciled 2026-09-22. This is the
operator-facing source of truth for the homelab `10.0.0.0/24` LAN. It records
only named infrastructure addresses, not every DHCP client on the home LAN.

## Address allocation

| Address or range | Owner | Assignment | State | Notes |
| --- | --- | --- | --- | --- |
| `10.0.0.1` | Rogers router | Router LAN address | Live | Default gateway for all entries below. |
| `10.0.0.67` | Secondary PVE IBM IMM2 | DHCP reservation | Operator-confirmed | Out-of-band management for the physical secondary server. Recheck after any router or IMM reset. |
| `10.0.0.98` | Primary PVE IBM IMM2 | DHCP reservation | Operator-confirmed | Out-of-band management for the physical primary server. |
| `10.0.0.181` | Ubuntu laptop | Existing reservation | Active | Main control-plane host; routes .221/.231 across Wi-Fi with proxy ARP. |
| `10.0.0.221` | `talos-cp-01` | Guest-configured static | Existing target identity | QEMU/systemd on Ubuntu .181; source PVE VM 100 is stopped and stale. |
| `10.0.0.222` | `talos-worker-01` | Guest-configured static | Existing target identity | VM 102 on primary PVE; primary-local persistent storage. |
| `10.0.0.223` | Secondary PVE | Static host management | Physical host target | Proxmox endpoint for the secondary server. |
| `10.0.0.224` | Primary PVE | Static host management | Existing host target | Proxmox endpoint for the primary server. |
| `10.0.0.225` | `talos-worker-02` | Guest-configured static, no router reservation | Active / Ready | VM 103 on secondary PVE; live acceptance passed 2026-09-19. |
| `10.0.0.230` | Existing LAN occupant | Undocumented | Occupied | Do not allocate. Identify and record the owner before changing the static block. |
| `10.0.0.231` | Talos API | Layer-2 virtual IP | Existing target identity | Not available to MetalLB Services. |
| `10.0.0.232-10.0.0.253` | Kubernetes Services | MetalLB | Reserved service range | The configured MetalLB pool includes `.231-.253`; `.231` is excluded in practice because it is the API VIP. Record individual assignments when created. |

The Rogers DHCP pool ends at `.220`. The lower boundary and every consumer
DHCP reservation are router-owned facts and must be exported from the Rogers
router before treating them as a complete inventory.

## Secondary-server and Kubernetes status

Secondary Kubernetes capacity is **active**, verified 2026-09-19. Both hosts
booted after the operator's DIMM move; each has 128 GiB installed and zero
reported corrected/uncorrected EDAC errors. Both PVE endpoints and IMM SSH
interfaces were reached. All three Talos nodes are Ready through API VIP .231.
Worker-02 passed cross-node Pod-IP, Service-IP and DNS tests in both directions,
including a gVisor stateless Pod. Temporary test resources were removed.
All 17 PVC and 16 PV identities/bindings match the pre-join baseline; protected
consumers remain on worker-01. See OpenSpec implementation log LOG-0093/0068.

Secondary CacheVault CVPM02 reports failed/replacement required. The RAID5
array is optimal, operating in protective write-through mode with disk cache
disabled. Replacement remains maintenance work; do not force write-back.

The secondary 200-GiB Nexus OCI cache disk and instance, Docker Hub/ECR proxying,
registry mirrors, Roles Anywhere refresher and `cache-registry.homelab.tfdraw.dev`
are deferred. No address or endpoint is activated for that cache. Worker-02
remains stateless with one OS disk; worker-01 retains its 1,200-GiB primary-local
data disk and existing protected PVC workloads.

## Historical addresses

`10.0.0.63` and `10.0.0.92` are former PVE management addresses. `10.0.0.181`
is the active Ubuntu control-plane host. Do not reuse the former PVE addresses.

## Change control

Before assigning an address, check the router reservation list, current ARP
neighbours, and the table above. Update this document, the Talos/PVE desired
configuration, and the OpenSpec record together. Never infer a live
Kubernetes-node state from a rendered OpenTofu plan.
