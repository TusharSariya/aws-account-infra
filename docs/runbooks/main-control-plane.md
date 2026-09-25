# Relocate the existing main control plane

Status: **accepted on 2026-09-22**. The laptop is the authoritative main control
plane. Physical sleep/wake, both-host-off operation, Wi-Fi reconnection and laptop
reboot passed. Applications and original submissions are restored. See the
[verification record](../../platform/main-control-plane/evidence/2026-09-21-preflight.md).
Source VM 100 is stopped and must not boot from its stale disk.

## Invariants and private paths

Keep cluster `homelab`, node `talos-cp-01`, MAC `02:42:00:00:01:00`, Talos address
`10.0.0.221`, API VIP `10.0.0.231`, all CA material and etcd state. The destination
has 2 vCPU, 4096 MiB, q35, source UEFI CODE/VARS, virtio-scsi-pci and the copied
100-GiB system disk. MAC-based Talos link selection preserves guest routes and VIP
ownership. Never bootstrap, generate replacement secrets, or join main workers
to the pilot. No images or credentials go into Git.

- Main source: primary PVE `10.0.0.224`, VM 100, system LV `/dev/pve/vm-100-disk-1`,
  EFI LV `/dev/pve/vm-100-disk-0`.
- Main destination: Ubuntu `10.0.0.181`, `/var/lib/main-control-plane/vm`,
  `main-control-plane.service` and `main-control-plane-network.service`.
- Laptop scripts: `~/main-control-plane`; main manifests: `~/main-platform`.
- Private credentials/checkpoints: `~/.local/share/main-control-plane/` (0700).
- Retired pilot: existing `~/talos-wifi-prototype` disks stay in place. Preserve its
  private configs, snapshots, user units and checksums under
  `~/.local/share/main-control-plane/pilot-retired`. Do not run its old network
  cleanup after main activation: it globally disables forwarding.

The dedicated laptop management key is `~/.ssh/main-proxmox`, authorized on PVE
only from `10.0.0.181` with SSH forwarding disabled. Protect it as a host-root
credential; revoke the matching `main-control-plane-management` key if abandoning
this migration. Do not use Pi-hole, Tailscale application proxies, Nexus or Argo
for recovery access. Keep private material and a checksummed copy off the laptop
as well as outside this repository before stopping the source.

## Preflight and network proof

1. Record `qm config 100`, `qm showcmd 100 --pretty`, source state, free space,
   laptop memory, routes, firmware geometry and current node/PVC/PV identities.
   Check all foreign active jobs and backups before disruptive operations. Worker
   02 was already NotReady/cordoned at the initial 2026-09-21 audit; that is not a
   successful new sleep test. Preserve dormant AI resources.
2. Run `prepare-wizard.sh` over an interactive SSH terminal. It keeps graphical
   boot, masks suspend targets, installs permanent KVM group permissions and
   root-owned services. It grants only the fixed `ops.sh` test/start/stop operations,
   not a root shell. The network helpers and services are not enabled automatically.
3. Confirm `.226` and `.227` against router reservations, this repository's address
   inventory, and duplicate-address ARP probes. They are outside DHCP and MetalLB.
   `ops.sh test-up` also ARP-probes both before use. Never use `.221` or `.231` for
   the proof while the source runs.
4. Run from the laptop:

   ```sh
   sudo -n /usr/local/lib/main-control-plane/ops.sh test-up
   sudo -n /usr/local/lib/main-control-plane/ops.sh test-verify
   sudo -n /usr/local/lib/main-control-plane/ops.sh test-down
   python3 ~/main-control-plane/firmware-probe.py
   ```

   The test uses an isolated namespace with the same /24 route and a second /32
   address. Prove guest-to-router, PVE and worker reachability, and PVE-to-both-test-
   addresses HTTP. Capture outputs outside Git. Additional UDP/cross-node Cilium
   checks remain mandatory after actual cutover. `network-proven` is created only
   on success. Remove failed test networks before retrying. The firmware probe uses
   source CODE/VARS copies with **no cluster disk or NIC**; its success proves QEMU
   compatibility, not a successful Talos boot.

Forwarding is enabled per interface. The isolated bridge proxy-ARPs the guest's
unchanged LAN route; explicit Wi-Fi proxy entries advertise only the VM's two /32
addresses. There is no Wi-Fi Ethernet bridge, NAT, address change or TLS bypass.
A retained pilot nftables chain has default-drop forwarding, so the helper inserts
only main-bridge/address exceptions there and records their handles for removal.
It does not change that chain's default policy. Unknown firewall blockers must be
inspected, not solved by flushing firewall rules. References:
[Linux proxy ARP/forwarding](https://kernel.org/doc/html/latest/networking/ip-sysctl.html),
[QEMU pflash](https://www.qemu.org/docs/master/system/qemu-manpage.html).

**Block cutover** for failed forwarding, unsuitable firmware, missing private
recovery copies, insufficient sparse-copy space, or missing credentials. Keep the
source running. Never silently change the API endpoint to bypass a blocker.

## Offline cutover

Stage Linux kubectl/talosctl plus the **main** kubeconfig, talosconfig and existing
secrets bundle under the private directory. The kubeconfig must retain its CA/client
credentials and use `https://10.0.0.231:6443`. Never use the pilot kubeconfig here.

`migrate.py preflight` verifies main identity/configuration, network proof, firmware
proof, an empty destination, at least 20 GiB free and disabled startup. Also check
the source thin-LV allocation and source export filesystem headroom; a 100-GiB
virtual disk need not occupy 100 GiB, but do not assume sparse export is small.
Take a private OpenTofu state backup (`tofu state pull > PRIVATE_FILE`) and stop
infrastructure applies for the cutover window.

`migrate.py cutover` journals every boundary. It captures fresh main etcd and
identity/recovery material, retires pilot user services with their prior state,
snapshots and gracefully shuts down the pilot, and checksums its stopped disks.
Also preserve and disable the root `prototype103-vm.service` and
`prototype103-network.service` startup units using interactive sudo; user-unit
disabling alone is insufficient. Do not stop the old network service while the
main VM runs, because its cleanup disables forwarding globally. The final recovery
wizard disables both units without invoking that cleanup before reboot.

It disables source autostart and enables Proxmox protection **before** gracefully
shutting VM 100 down. It never force-stops a failed shutdown.

Only while the source is confirmed stopped does it convert the source LV to sparse
qcow2, compare logical contents with `qemu-img compare`, and copy/checksum disk and
firmware to the laptop. PVE exposes only **540672 bytes** from its 4-MiB EFI LV as
VARS; the tool preserves the whole LV privately and copies that exact visible
prefix for QEMU. The 3653632-byte source CODE plus VARS make the original 4-MiB
firmware pair. No guest disk/controller conversion or replacement is performed.

The root dispatcher independently rechecks source stopped/onboot=0/protection=1,
checksums, EFI sizes and `qemu-img check` before activating real /32 routes and
starting the destination. A destination-starting journal is written **before**
launch because etcd can accept writes immediately. Never restart VM 100 merely
because destination acceptance has not finished.

If the command fails, inspect the journal. It deliberately does not try an
unattended reverse migration. Do not rerun over an existing checkpoint, copy or
journal. Source-stopped/copy-incomplete is distinct from destination-started.

## Memory exhaustion (2026-09-25)

Symptoms: `10.0.0.231` unreachable ("no route to host") while `10.0.0.221`
answers `talosctl`; `talosctl -n 10.0.0.221 services` shows etcd, kubelet and cri
health failing; `dmesg` full of `OOM controller triggered` for BestEffort
kube-system pods; the laptop shows load above 60, 60%+ iowait and 200 MB/s of
sustained reads from `system.qcow2`. The power coordinator logs `reconcile-error`
continuously and cannot retire either host.

Diagnose without touching the guest: `talosctl -n 10.0.0.221 -e 10.0.0.221 memory`,
`processes -s rss`, `logs etcd | grep -E 'slow fdatasync|took too long'`, and the
QEMU monitor (`query-blockstats`, `screendump`) on `/var/lib/main-control-plane/vm/qmp.sock`.
Recovery is `ops.sh stop` then `ops.sh start` once the reviewed budget in
`live/talos/homelab/README.md` (kubelet reservations, `GOMEMLIMIT`, audit policy,
Cilium requests, 10 s lifecycle cadence) has been applied or is queued to apply
immediately after; a restart alone drifts back into the same state. Release any
durable CI power hold afterwards with its receipt or, when the receipt is gone,
after confirming the owning run has ended.

## Placement and ownership

After identity/network checks, generate and server-dry-run the
[placement plan](../../kubernetes/platform/main/placement/plan.py), inspect it and
apply with a new private output directory. UID/spec tests prevent
stale writes. Wait for each essential and platform Deployment rollout. Apply
controller-owned ProxyClass/listener configuration; do not patch ephemeral Pods.
Persist corresponding values in existing Helm release configuration before any
later Helm upgrade. Audit webhooks again: no sleeping worker webhook may gate
kube-system Pods, Nodes, Secrets, Leases or essential Deployments. The initial
CNPG/Kueue audit met that requirement; keep fail-closed application policy scoped
away from essential recovery rather than changing every webhook to Ignore.

After acceptance, retire IaC ownership without destroying the preserved VM:

1. Save the private current primary OpenTofu state and reviewed plan.
2. If state actually owns it, remove only `proxmox_virtual_environment_vm.guest["talos-cp-01"]` with
   `tofu state rm 'proxmox_virtual_environment_vm.guest["talos-cp-01"]'`.
3. Remove only `talos-cp-01` from the primary `vms.tfvars` map. Validation permits
   only worker 01 / VM 102 and rejects reintroducing VM 100, including under a renamed key.
4. Run a refreshed plan with the existing private provider configuration. Require
   no source recreation/start/deletion and no worker or disk replacement. Do not
   apply any unexplained drift. Keep VM 100 manually owned, stopped, protected,
   and onboot=0. Record the destination ownership in the address inventory.

The original migration checkout was stale: its absence of local state did not
prove absence of remote ownership. During reconciliation on 2026-09-22 the
current main branch's S3 state (`proxmox/homelab/terraform.tfstate`) was inspected
and backed up. Exactly VM 100 was removed with locking; worker 01's complete
state entry was verified unchanged. The state-based `-refresh=false` plan has no
VM changes. A refreshed provider plan requires waking Proxmox separately.
Never apply the obsolete pre-migration branch or restore an old state over the
retirement. The preserved source disk is stale and must remain stopped.


## Required acceptance evidence

Do not check these off based on a rendered manifest or process start:

- `migrate.py verify`: original node and namespace UIDs, all baseline PV/PVC UIDs,
  bindings, classes and affinities; API readyz; same etcd member and healthy etcd;
  compare CA/API certificate identities, endpoints and SANs with the private baseline.
- Main workers regain connectivity; run existing two-worker smoke in both directions
  for Pod-IP, Service-IP and DNS. Confirm Cilium overlay traffic over Wi-Fi and
  kubelet TLS; CoreDNS and Cilium operator are on the laptop. Check upstream DNS
  forwarding does not depend on sleeping Pi-hole. Keep CP taints.
- `capacity.py --seconds 600 --output PRIVATE.json` during four bounded worker Jobs:
  host and guest MemAvailable >=512 MiB every sample; no sustained swap I/O
  >=64 KiB/s for 60 seconds; no gaps >45 seconds. Check Ready nodes, healthy
  controllers, no OOMs and no unexpected restarts separately. Sample again with
  monitoring, then with Argo; keep the graphical desktop running.
- Write a private `control-plane` acceptance receipt only after the above checks.
  Install monitoring with its gated installer. Prove all scrape targets expected
  awake are up, provisioned dashboards have samples, all five claims bind to
  primary storage, and logs are searchable after replacing an opted-in canary Pod.
  Ordinary unsanitized canary output must not appear in Loki.
- Exercise an explicit temporary alert, observe firing and resolution in Prometheus
  and Alertmanager, then remove it. Alerts are UI-only until notification routing
  is separately configured. Query a known log marker and historical metric before
  and after monitoring Pod replacements and a graceful worker restart. Compare all
  claim/PV UIDs again. No deletion/recreation of claims is permitted.
- Only then write monitoring acceptance and install Argo. Verify core health and
  recovery after worker restart with zero Applications and no repository Secret;
  no application changes, automatic sync or pruning occur.
- Run secondary sleep/wake, then primary sleep/wake, then both off together through
  [the manual procedure](manual-server-sleep.md). Observe laptop API/etcd/DNS
  throughout. Finally test laptop reboot and Wi-Fi reconnection with both hosts off.
  Verify KVM, networking, guest startup, IP/VIP advertisement and DNS recover
  without a worker-host or Kubernetes-managed proxy dependency.

After the initial control-plane acceptance receipt, enable main VM autostart with
`sudo -n /usr/local/lib/main-control-plane/ops.sh accept` before the reboot test.
This enables startup but does not certify physical-host or reboot recovery.
Do not call recovery proven until those tests have actually passed. Keep all evidence timestamps and
incomplete/blocked checks explicit.

## Rollback

If destination never started: leave it stopped, remove test/real advertisement,
verify no QEMU holds its disk, and restore source onboot/protection settings from
checkpoint before starting VM 100. Preserve failed copy/checkpoint material.

After destination **ever starts**, treat it as having accepted writes. Quiesce jobs
and applications; take a new destination etcd snapshot and private checkpoint;
gracefully stop Talos and the destination service, verify QEMU closed the disk,
then withdraw /32 routes/proxy entries. Convert the latest stopped destination
system disk back to raw on PVE, compare and checksum it, and restore the latest
VARS visible prefix into the preserved EFI LV without changing its remaining bytes.
Take a private backup of the original LVs before overwriting either. Ensure the
laptop startup service is disabled and its fencing marker revoked before starting
VM 100. Verify identity and storage again. Restore IaC ownership only by explicit
import and reviewed plan. If latest state cannot be transferred consistently,
keep both copies stopped and use the saved recovery material; never boot stale etcd.

Monitoring and Argo can be rolled back independently by scaling their own workloads
to zero, preserving claims, namespaces, Secrets and CRDs. This never rolls back
existing PostgreSQL, Pi-hole, Nexus or dormant AI data.
