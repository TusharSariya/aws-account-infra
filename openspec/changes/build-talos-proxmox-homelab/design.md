## Context

See `proposal.md` for motivation and `specs/homelab-provisioning/spec.md` for the behavior contract. The target is one IBM System x3550 M4 running Proxmox with 24 physical cores, 48 logical CPUs with SMT enabled, two NUMA nodes, 188 GiB usable memory, and an approximately 1.75 TiB LVM-thin pool backed by an aging ServeRAID array. The current branch documents the target but contains locally validated Proxmox definitions and Talos generation tooling, with no live deployment.

Implementation combines operator-driven Proxmox and firmware actions with version-controlled configuration. Because some actions occur outside Git, the repository needs an execution record that distinguishes planned work from observed results.

## Goals / Non-Goals

**Goals:**

- Produce a staged build whose next action, current state, evidence, and recovery path are reviewable.
- Preserve separate control-plane resources and enforce sandbox runtime policies on a shared worker.
- Pin every acquired artifact and keep custom Talos ISO and installer schematics consistent.
- Make the desired state reconstructable from Git and make important state recoverable off-host.

**Non-Goals:**

- Claim physical high availability from multiple VMs on one server.
- Deploy all roadmap applications as part of the initial platform build.
- Place live PostgreSQL data, Prometheus data, or etcd state on NFS.
- Store credentials or complete sensitive command output in Git.
- Treat a Proxmox snapshot as an application-consistent or off-host backup.

## Decisions

### Use one OpenSpec change with phase-gated tasks

The initial host preparation, VM creation, Talos bootstrap, worker-local storage, and recovery verification remain one change because they collectively deliver the first usable platform. Tasks are grouped into acceptance-gated phases, and an incomplete or unsafe phase blocks dependent work.

Alternative considered: one change per VM. That makes individual changes smaller but obscures cross-VM capacity, startup order, networking, and trust-boundary acceptance criteria.

### Record execution separately from planned tasks

`tasks.md` expresses intended work and completion status. Apply creates `implementation-log.md` beside the planning artifacts and appends one entry per executed operation. Entries use RFC 3339 timestamps and monotonic sequence numbers and contain:

- operator and target;
- planned action and exact sanitized command or UI path;
- observed result and non-sensitive evidence;
- versions, schematic IDs, image references, and digests when relevant;
- deviation or blocker;
- rollback or recovery action; and
- the task identifier the entry supports.

Corrections append a new entry that references the superseded sequence number. Git history supplies tamper evidence, while the entry convention preserves the operational narrative.

Alternative considered: use task checkboxes as the log. Checkboxes cannot capture failed attempts, observed output, deviations, or recovery evidence.

### Use two VMs and two Talos Image Factory schematics

Operator-approved revision on 2026-09-12 consolidates application compute and storage into one shared worker. A small separate control plane retains its own fixed memory and can remain available during worker maintenance. Both VMs still share one host and disk array; neither arrangement provides physical high availability.

| VM | ID | vCPU | RAM | Disks | IP | Startup |
|---|---:|---:|---:|---|---|---:|
| talos-cp-01 | 100 | 2 | 4 GiB | 100 GiB OS | 10.42.0.220 | 1 |
| talos-worker-01 | 102 | 38 | 172 GiB | 100 GiB OS + 1,200 GiB data | 10.42.0.222 | 2 |

Totals: 40 vCPUs, 176 GiB RAM and 1,400 GiB primary disks plus two EFI volumes. Observed host memory is 188 GiB, leaving approximately 12 GiB for host processes, QEMU overhead and cache. The observed 1,795.992-GiB thin pool leaves approximately 395.992 GiB before auxiliary volumes. These are initial budgets, not guarantees of available application memory or dedicated CPU throughput. Recheck host capacity before creation and measure pressure under actual workloads. Serial model execution must leave worker memory for Kubernetes and Celery services.

The control plane keeps the qemu-only schematic. The shared worker uses the previously acquired qemu-plus-gVisor schematic and ISO, with the immutable matching installer digest. Talos v1.13.9 and Kubernetes v1.36.3 remain pinned. Install disks are /dev/sda; the worker's separate /dev/sdb is reserved for a Talos-managed user volume mounted at /var/mnt/local-path-provisioner in phase 6. Formatting that disk requires verified guest identity and disk mapping first.

There is no Debian NAS or separate sandbox VM. The old Debian ISO and retired DHCP reservations may remain unused; no deletion of live host files is required. IDs 101 and 103 and addresses .221 and .223 remain reserved but have no desired VM. Keep existing control-plane and worker MAC identities.

Trusted services and sandbox workloads share the worker. Label it workload.security/shared=true, with no sandbox NoSchedule taint that would block ordinary services. Keep the control plane unschedulable for applications. Sandbox namespaces still require gVisor RuntimeClass, restricted admission, explicit shared-worker placement, network policies and resource limits. This accepts removal of the old dedicated VM and physical-core trust boundary. gVisor is not equivalent to separate VM isolation.

SMT remains enabled. CPU/NUMA tuning remains deferred; neither affinity nor reserved physical cores is claimed. A 172-GiB worker necessarily spans host NUMA memory. Do not preserve the former single-NUMA sandbox placement requirement or make deferred tuning a creation prerequisite. Use host scheduling initially and measure before tuning.

Alternatives considered: four VMs imposed storage and trust separation the operator no longer wants; one massive VM saves little control-plane overhead while coupling its resource pressure and maintenance to every application. Two VMs are the approved compromise.

### Manage guest hardware with a dedicated OpenTofu root

Task 3.1 implements `live/proxmox/homelab` with `bpg/proxmox` 0.112.0 and a provider lockfile. Non-secret per-guest inputs live in `config/environments/proxmox/homelab/vms.tfvars`; deploy unit `proxmox-homelab` is enabled for GitHub CI through Tailscale OIDC, with a read-only Proxmox plan identity and a separate apply identity. Offline mocked-provider plans verify the hardware contract without a live API operation. The initial lifecycle defaults are stopped and no host autostart; phase 4 records the explicit boot/autostart transitions. Both Talos VMs enable the QEMU guest agent.

Trusted API access and a separate S3 backend key are now configured; a live speculative plan passed. State restore and remaining readiness checks remain open. The default approval flag blocks provisioning, while the preview-only helper assumes future approval without applying. The operator deferred the clean-machine restore test; this is not a claim of recovery completion. The initial provider installation reported an expired publisher signing-key warning; preserve this as a recovery-bootstrap issue to resolve rather than disabling verification. See the root README and LOG-0040 for validation scope and limitations.

### Host-level Tailscale administration

The operator reports Tailscale installed directly on `pve` on 2026-09-12. Treat installation as reported evidence, not proof of enrollment, remote reachability or route approval. Record the installed version, package source, service persistence, tailnet identity and non-secret connection settings during verification.

Use Tailscale on the Proxmox host for private UI (HTTPS 8006) and ordinary SSH (TCP 22) from authorized administrator devices. Keep Proxmox authentication and SSH keys; Tailscale SSH is a separate optional feature, not implied by installing the client. Preserve trusted TLS verification for automation and document the certificate trust path. Do not expose administration through public port forwarding, Cloudflare Tunnel or Tailscale Funnel.

Plan Proxmox as the subnet router for `10.42.0.0/24` so authorized administrators can reach Talos and selected service addresses without adding Tailscale to every Talos VM. Subnet-route advertisement, tailnet route approval, client route acceptance, forwarding and the operator-approved access policy must be recorded and verified before this path is accepted. No route advertisement or firewall change is inferred from the installation. Review default subnet SNAT and return paths explicitly; management access is not proof that an external GPU worker has the bidirectional node/Cilium connectivity it needs.

The laptop remains the physical internet gateway and must be powered on for remote access. Its existing local SSH path and the Proxmox console remain recovery fallbacks. Tailscale on the laptop is optional separate work, not a completed installation. No third VM or Kubernetes-hosted operator is needed for host recovery access.

Include the package/version source, service setup, tags, tailnet grants/ACLs, approved routes, certificate handling, key-expiry policy, administrator account recovery and device re-enrollment/revocation in the DR procedure. Keep auth keys and node private state out of plaintext Git. Enrollment and recovery access must not depend solely on this Kubernetes cluster or its Authentik instance. Verify UI and SSH from a separate internet connection such as a phone hotspot, and verify local fallback without Tailscale before declaring remote recovery ready.

References: [Proxmox integration](https://tailscale.com/docs/integrations/proxmox), [subnet route acceptance](https://tailscale.com/docs/reference/route-injection), [subnet SNAT and routing](https://tailscale.com/docs/features/site-to-site).

### Separate planning, safe inspection, and live mutation

Repository planning does not authorize live operations. During apply, read-only inspection and artifact acquisition may proceed first. Firmware, BIOS, RAID, storage allocation, networking, OS installation, and cluster bootstrap require an explicit pre-action record and operator confirmation when their effects are destructive or difficult to reverse.

## Recovery completeness applies to each operation

Operator requirement recorded 2026-09-12: all completed steps must be reproducible for full disaster recovery. An audit entry proves what happened, but does not by itself supply a rebuild procedure. Each operation must map to versioned desired state and repeatable automation, or a precise manual procedure for hardware/console actions, with inputs, dependencies, verification, and secret recovery references. Never recover prerequisites solely through a service that depends on the failed cluster.

The recovery boundary includes a clean administrator machine, the laptop's Ubuntu and NetworkManager shared-network bootstrap, SSH public-key provisioning and client aliases, router/address dependencies, Proxmox installation and storage layout, guests, Talos, worker-local storage, and accepted application state. Private credentials remain outside plaintext Git. Their encrypted backup or reissuance procedure and independently available decryption/recovery access must be documented and tested. Set explicit recovery-time and data-loss objectives before declaring full DR accepted.

Current gaps are follow-up work, not evidence that the first nine recorded operations did not occur:

- The two verified Mac baseline archives are sanitized empty-host reconstruction inputs, not full Proxmox restores. They omit `/etc/ssh`, `/etc/pve/priv`, `/etc/pve/user.cfg`, and `/var/lib/pve-cluster/config.db`; no complete host-reinstallation rehearsal is recorded.
- Those off-host baselines precede the laptop network migration. Off-site retention and recovery of the administrator's credentials and ignored local inventory are not verified.
- Several provisioning scripts and the OpenSpec change are untracked in the current checkout. Local files do not establish an independently recoverable Git revision.
- Artifact sources and checksums are logged, but exact long-term availability of installers, packages and Talos schematic inputs must be established through archived artifacts or verified reacquisition procedures. An unpinned future `apt full-upgrade` does not reproduce the current package set.
- The prepared network wizard requires an existing laptop hostname, shared connection, Proxmox reservation and reachable server, and refuses an existing guest-reservation file. It is a one-time change helper, not fresh-machine bootstrap or idempotent reconciliation. Retain its intended state in durable configuration and replace these assumptions with a tested bootstrap/reconcile path before treating networking as DR-ready.

The restore rehearsal must start with a clean management environment and assume both laptop and Proxmox are lost. Recover networking/access first, then host and storage, guests, cluster, and worker data. Use isolated replacements or disposable test infrastructure; do not destroy running systems as a test. Component tests remain necessary but do not substitute for the dependency-ordered rehearsal.

## Risks / Trade-offs

- [Aging ServeRAID disks fail during build] -> Export configuration first, inspect controller and disks, avoid treating the array as durable backup, and establish off-host recovery before important state is accepted.
- [Thin-pool overcommit causes broad guest failure] -> Reconfirm actual capacity, retain unallocated recovery headroom, disable discard as documented, and alert on pool utilization.
- [A manual operation is not reproducible] -> Record the exact operation and result, then convert stable configuration to repository-managed automation where practical.
- [The audit log leaks secrets] -> Sanitize output, record identifiers or hashes instead of secret bodies, and reject secret-bearing evidence from Git.
- [OpenSpec artifacts duplicate PR #31 plans] -> Reference the plans for background while keeping OpenSpec focused on enforceable requirements, execution decisions, tasks, and observed evidence.
- [One host outage stops every VM] -> State the limitation explicitly and rely on Git plus application-native off-host backups and restore testing, not VM count.
- [Shared-worker workloads affect each other] -> Require sandbox runtime/admission controls and resource limits; retain the operator-approved loss of separate VM isolation explicitly. CPU/NUMA tuning is deferred.

## Migration Plan

1. Acquire and verify installation artifacts without changing running guests.
2. Capture the host baseline and export recoverable Proxmox configuration.
3. Resolve firmware, RAID, virtualization, SMT, network, and capacity gates.
4. Create the control plane followed by the shared worker after network and recovery gates pass.
5. Install and bootstrap Talos, then prove node identities, extension separation, networking and sandbox runtime enforcement.
6. Configure worker-local persistent storage, monitoring and independent backups.
7. Exercise reconstruction and data restore and resolve audit-log blockers.

Rollback is phase-specific. Before Talos contains important state, a failed VM can be destroyed and recreated from configuration. Worker data-disk rollback requires a verified backup once data exists. Host firmware or RAID operations use vendor-supported recovery procedures and must not begin without the corresponding configuration backup and recovery record.

## Deferred tuning

CPU affinity and NUMA exposure remain optional later tuning. Network and recovery prerequisites are tracked in tasks 2.5, 2.7 and 2.8; they remain required before creation. Earlier implementation-log entries describe the previous four-VM design and are preserved as history.

### Optional Tailscale access hardening

Operator decision: retain the supplied default allow-all tailnet network policy for the initial personal build. Tailnet membership is the accepted network trust boundary; all members/devices can reach advertised destinations broadly. This does not make Serve public. The proposed account/port-scoped policy in `config/environments/proxmox/homelab/tailscale/policy.json` is an unapplied optional improvement, including removal of Funnel permission. Revisit before adding other users or less-trusted devices. Do not block VM creation or subnet-route acceptance on adopting it. Tailnet-only management, existing host authentication and recovery prerequisites remain required.

### AWS recovery destination preparation

Operator selected AWS for independent backups. `live/aws/staging/workloads/homelab-recovery` now defines a dedicated bucket and separate upload/restore IAM policies using the existing encrypted-bucket module, with independent backend state. PR #47 deployed the bucket through OpenTofu CI. LOG-0059 through LOG-0061 record live storage verification, canary testing and the actual encrypted bootstrap archive's same-Mac restore. Initial uploads use the existing administrator login; optional Roles Anywhere identity remains disabled. Task 2.8 remains open for independent recovery and the other acceptance criteria. See docs/plans/homelab-recovery.md for the current recovery entry point.

### Daily etcd retention and independent execution

Use a main-branch GitHub schedule at 06:17 UTC and manual dispatch. Reuse the
existing prod Talos secret and Tailscale OIDC route; a dedicated AWS role grants
only single-key upload/readback, recovery KMS access through S3 and a success
metric. The runner has no age decryption key. Store its public recipient in Git,
and keep the private identity on the administration machine plus independently
recoverable custody. Test local decryption of the first exact S3 version.

Write the same versioned etcd/latest.tar.gz.age key every run. Configure only
noncurrent-version expiry at 30 days for etcd/, with no current expiration.
This retains the last backup indefinitely even when schedules stop. Age counts
from supersession, not original creation; S3 deletion is asynchronous and honors
the existing 30-day governance Object Lock. Do not add delete permission to the
backup runner or apply this policy to independent bootstrap/host archives.

Only verified upload/readback publishes the success metric. A CloudWatch
30-hour missing-heartbeat alarm uses the existing security-alert SNS route and
runs independently of GitHub, the laptop and Kubernetes. This detects missed
schedules as well as backup failures. No isolated etcd restore is implied.
