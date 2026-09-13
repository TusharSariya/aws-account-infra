## 1. Audit Foundation and Installation Artifacts

- [x] 1.1 Create `implementation-log.md` with the approved sequence-numbered entry template and verify it contains fields for timestamp, operator, target, task, action, sanitized command or UI path, result, evidence, deviation, superseded entry, and rollback
- [x] 1.2 Generate the Talos v1.13.9 amd64 trusted schematic with only `siderolabs/qemu-guest-agent`, download its `metal-amd64.iso` to Proxmox `local` ISO storage, and verify the log records the source URL, schematic ID, matching installer image, extension list, local filename, and digest
- [x] 1.3 Generate the Talos v1.13.9 amd64 sandbox schematic with `siderolabs/qemu-guest-agent` and `siderolabs/gvisor`, download its `metal-amd64.iso` to Proxmox `local` ISO storage, and verify the log records the source URL, schematic ID, matching installer image, extension list, local filename, and digest
- [x] 1.4 Download the current Debian 13 amd64 netinst ISO from an official Debian source, pin its exact point release, verify it against the signed SHA-512 manifest, and record the verification evidence
- [x] 1.5 Run `pvesm list local --content iso`, verify all three pinned ISOs are present exactly once, and record the sanitized output and local digests

## 2. Proxmox Host Readiness

- [x] 2.1 Export the Proxmox network, storage, repository, and host configuration to a recoverable off-host destination and verify the archive can be listed without exposing secrets in Git
- [x] 2.2 Inspect the ServeRAID logical-disk RAID level, cache and battery or flash protection, patrol-read state, grown defects, and every physical disk, and verify no unresolved unsafe finding remains before allocation
- [x] 2.3 Record the installed IBM BIOS, ServeRAID, NIC, IPMI, and Proxmox versions; perform separately approved updates where required; and verify the final versions and recovery paths are logged
- [x] 2.4 Verify VT-x, VT-d or IOMMU, and ECC reporting are enabled, retain SMT by approved operator decision, and verify `lscpu` exposes 24 physical cores, 48 logical CPUs, two threads per core, and two NUMA nodes with zero EDAC errors
- [ ] 2.5 Inspect `vmbr0`, management access, routes, DNS, DHCP reservations, the MetalLB exclusion range, and available addresses; then record approved VM IDs, MAC addresses, guest IPs, API endpoint, and startup order
- [x] 2.6 Reconfirm physical, `local`, and LVM-thin capacity after host changes, calculate the exact proposed allocations and retained headroom, and verify the thin pool is healthy before creating any guest disk

- [ ] 2.7 Implement and verify a fresh-machine recovery procedure for the administration environment, laptop OS/network/SSH bootstrap and Proxmox OS/storage baseline; preserve non-secret identities and desired state, define secret recovery or reissuance inputs, and reconcile repeated runs without relying on the existing laptop, SSH aliases or prior wizard state
- [ ] 2.8 Define recovery-time and data-loss objectives; preserve a reviewed Git revision independently of the working checkout, capture a current post-change baseline, and verify encrypted off-site recovery material and independent recovery access for required secrets, inventory, installers, package/version inputs and configuration before guest creation

- [x] 2.9 Verify the operator-installed Tailscale client on pve: record version/source, service persistence, enrollment and non-secret identity, record the operator-approved current access policy, and prove authenticated HTTPS/SSH from outside the home network with documented TLS handling
- [x] 2.10 Configure and validate the planned Proxmox subnet route for 10.42.0.0/24 with route approval, client acceptance, the operator-approved default access policy and forwarding/return paths; prove access to available intended endpoints and retain separate guest/GPU runtime checks
- [ ] 2.11 Document and verify reproducible Tailscale installation, re-enrollment/revocation, policy/routes and key-expiry recovery with independent administrator access and a tested local fallback; keep private state and auth keys outside plaintext Git

## 3. Reproducible Guest and Talos Configuration

Prerequisite: review the recovery-foundation gaps in 2.7 and 2.8 before guest creation. The operator deferred the clean-machine restore test; retain it as untested and do not mark the recovery tasks complete. Other network/state prerequisites remain. Task IDs remain stable; completed task evidence is preserved.

- [x] 3.1 Add repository-managed desired-state definitions for the two VMs using 2/38 vCPUs, 4/172 GiB RAM, 100-GiB OS disks and a 1,200-GiB worker data disk, preserving OVMF, Q35, VirtIO SCSI, fixed memory, bridge and no hotplug/discard; verify the rendered plan matches the design table
- [x] 3.3 Generate Talos machine configuration from non-secret patches with Talos v1.13.9, Kubernetes v1.36.3, CNI `none`, the stable API endpoint, correct install disks, and installer references matching each ISO schematic; verify generated secret-bearing files are excluded from Git
- [x] 3.4 Add and run static validation for Proxmox desired state and generated Talos configuration, verifying two-node capacities, identities, version pins, installer/ISO schematics, disk separation, control-plane scheduling, shared-worker labels, absence of obsolete sandbox taints and secret exclusions

## 4. VM Creation

- [x] 4.1 Resolve and log the exact `talos-cp-01` target, create its 2-vCPU, 4-GiB, 100-GiB VM, and verify its rendered Proxmox configuration and Talos maintenance-mode boot
- [x] 4.3 Resolve and log the exact talos-worker-01 target, create its 38-vCPU, 172-GiB VM with 100-GiB OS and 1,200-GiB data disks, and verify rendered Proxmox settings and Talos maintenance-mode boot
- [x] 4.5 Verify startup order is control plane then shared worker, QEMU Guest Agent matches the installed extensions, and record a sanitized qm config inventory

## 5. Talos Cluster Foundation

- [x] 5.1 Apply the control-plane machine configuration to the verified target and disk, bootstrap etcd exactly once, and verify Talos health plus API access at the stable endpoint
- [x] 5.2 Apply the shared-worker configuration and verify the node joins with its shared label, expected resources, QEMU Guest Agent and gVisor, without a sandbox NoSchedule taint
- [x] 5.4 Install pinned Cilium v1.20.1 in VXLAN mode with kube-proxy retained, and verify node readiness, CoreDNS, pod networking, service routing, and `kubeProxyReplacement=false`
- [ ] 5.5 Install the gVisor RuntimeClass and sandbox admission/network/resource controls on the shared worker; verify trusted services can coexist and sandbox pods without the required runtime or safe settings are rejected
- [x] 5.6 Capture an encrypted Talos etcd snapshot and reconstruction inputs in their approved off-host locations, then verify the snapshot metadata without committing kubeconfig, `talosconfig`, or machine secrets

- [x] 5.7 Implement and execute daily encrypted etcd backup through GitHub CI with dedicated OIDC permissions; verify exact-version upload/readback, local decryption, independently saved private recovery key and missing-backup monitoring
- [x] 5.8 Deploy and verify S3 noncurrent-version expiration after 30 days for daily etcd backups with no current-version expiration; prove successive backups create versions of one key and the runner has no deletion permissions

## 6. Worker-local Storage and Backup Foundation

- [x] 6.1 Prepare the Talos user-volume configuration selecting the verified worker data disk, mount at /var/mnt/local-path-provisioner and local-path provisioning; validate the config and ensure the OS disk cannot be selected
- [x] 6.2 Apply the worker data-volume configuration only after verifying /dev/sdb identity and size; verify the filesystem mount and persistence across a worker reboot without modifying the OS disk
- [x] 6.3 Define worker-local storage classes, retention and application capacity limits for model files, Celery services and durable data; verify representative PVC binding and read/write persistence
- [ ] 6.4 Configure independent encrypted backups and application-consistent export procedures for accepted worker data; verify backup access does not depend on this cluster and a test backup succeeds
- [ ] 6.5 Add worker disk/filesystem and Proxmox thin-pool capacity monitoring at 70/80/90 percent plus host memory-pressure monitoring; verify alert behavior without filling storage

## 7. Recovery and Acceptance

- [ ] 7.1 Reconcile every completed task with at least one non-secret implementation-log entry, verify failures and corrections remain visible, and run a secret scan over all OpenSpec artifacts
- [ ] 7.2 Recreate one disposable pre-stateful Talos VM from repository configuration and verify its Proxmox settings, schematic, machine configuration, and node identity match the recorded desired state
- [ ] 7.3 Exercise the documented etcd recovery procedure in a safe disposable or isolated context and verify the cluster control plane can be recovered without Authentik, Argo CD, or the NAS
- [ ] 7.4 Exercise worker storage reconstruction and a checksum-verified test-file backup and restore, plus application-native recovery for accepted databases; record measured results without copying live database files
- [ ] 7.5 Run the homelab provisioning acceptance scenarios, resolve or explicitly block every failure, run `openspec validate build-talos-proxmox-homelab --strict`, and verify the change is ready for implementation review or archive

- [ ] 7.6 Rehearse full disaster recovery in isolation from a clean administration environment, assuming the laptop and Proxmox are both lost; recover access/networking, host/storage, guests, cluster and accepted durable data in dependency order, verify service behavior and replayability, and record achieved recovery time/data loss against objectives with all unresolved blockers explicit

## 8. Automation Simplification (next, before new feature work)

Operator-approved planning revision: implement 8.1-8.5 before continuing new feature work in 6.4-6.5. Keep existing backups and services operating throughout. Task 8.1 inventory is recorded in docs/plans/homelab-automation-audit.md; tasks 8.2-8.5 remain pending and no refactor is claimed complete.

- [x] 8.1 Inventory deployment, tool setup, validation, secret handling, integration-test and backup responsibilities and all CI/local recovery callers; record which native mechanism replaces each responsibility and justify each retained helper
- [ ] 8.2 Move routine orchestration into named GitHub Actions steps, consolidate pinned tool setup and move suitable constraints into blocking OpenTofu validation; preserve focused live/plan guards, original Talos identity, ephemeral/write-only secrets and sanitized diagnostics
- [ ] 8.3 Separate targeted PVC/network integration suites into visible affected-change and manually dispatched jobs with acceptance gating; retain routine readiness checks and make reboot/recovery rehearsals explicit operations rather than hidden apply behavior
- [ ] 8.4 Consolidate snapshot preparation and verified encrypted upload behind one focused backup command; preserve schedule, format/restore compatibility, exact-version readback, receipts, OIDC permissions, heartbeat/alarm, independent key custody and S3 retention semantics
- [ ] 8.5 Prove migration parity with an authenticated no-change plan, negative safety/secret tests, targeted integration acceptance and a real encrypted backup download/decryption/integrity round trip; update all callers/recovery instructions, remove redundant wrappers and record rollback to a known working revision

## 9. Browser-based Kubernetes Dashboard

Schedule after automation simplification (8.2-8.5); product selection remains open and this planning task does not authorize a live deployment.

- [ ] 9.1 Select and deploy a maintained browser-based Kubernetes dashboard through reviewed Helm/OpenTofu GitHub CI; provide authenticated tailnet-only HTTPS access with read-only Kubernetes permissions by default, verify nodes/pods/deployments/logs/PVC views and denied unauthorized access, and document the URL, login, pinned configuration, resource budget and reproducible rebuild/removal procedure without exposing credentials

## Retired task IDs (not completed)

Operator-approved two-VM revision, 2026-09-12: 4.2 (NAS VM), 4.4 (sandbox VM) and 5.3 (sandbox join) are removed from active scope. Task 3.2 (dedicated sibling/NUMA placement) remains deferred tuning, no longer an implementation gate. These tasks were not executed. IDs are not reused. Completed artifact acquisition, including the unused Debian ISO, remains historical evidence. Phase 6 now implements worker-local storage and independent backups; 7.4 tests that recovery.

## Optional improvements (not deployment gates)

- Tailscale account/port-scoped grants and removal of Funnel permission: deferred by operator. Candidate policy is `config/environments/proxmox/homelab/tailscale/policy.json`, not applied. Before future adoption, validate it in Tailscale, test permitted and denied identities and preserve a rollback copy. Revisit when membership or device trust changes.

- Talos soft-reboot reliability: the initial control-plane installation reboot stalled in virtnet_poll after disk sync; a one-time pre-bootstrap Proxmox reset recovered it (LOG-0069). Investigate before relying on unattended reboots; no durable workaround is claimed.

Operator deferral, 2026-09-13: Task 5.5 (gVisor RuntimeClass and sandbox admission/network/resource controls) is deferred at the operator's request. The installed gVisor extension alone does not enforce sandboxing; no untrusted-workload isolation is accepted. Task remains unchecked.
