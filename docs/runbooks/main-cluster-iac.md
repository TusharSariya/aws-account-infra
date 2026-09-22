# Main-cluster IaC ownership

Configuration reconciliation is on `fix/main-cluster-iac-reconciliation`, based on
current main, rather than the stale `docs/talos-homelab-plans` checkout used during
migration. Both physical application hosts normally remain intentionally off.
An approved temporary wake on 2026-09-22 verified refreshed Proxmox plans and
permissions. Talos and application Helm upgrades use the reviewed CI apply
workflow; PR 117 records the rollout checks and execution status.

| Layer | Canonical owner |
| --- | --- |
| Laptop VM, firmware contract, routed Wi-Fi, systemd | `platform/main-control-plane/` |
| Primary worker hardware | `live/proxmox/homelab`, existing S3 state |
| Secondary worker hardware | `live/proxmox/homelab-secondary`, preserved private local state |
| Talos machine configuration | `config/environments/proxmox/homelab/talos`, generated with existing private secrets |
| Existing Helm releases | `live/talos/homelab`, `live/kubernetes/homelab`, `live/kubernetes/homelab-ci` |
| Monitoring and Argo CD | `kubernetes/platform/main`, reviewed Kustomize installation |
| Temporary sleep state | Laptop's private maintenance journal; not a new steady-state Helm release |

Every existing Helm resource now invokes the shared placement post-renderer with
an explicit namespace. Kueue chains its existing admission filter before that
renderer. The renderer hash participates in release inputs, and changes select
all three deployment roots in CI. This preserves primary platform/storage
placement on normal upgrades, without changing dormant AI specs or storage
identities. Talos apply also reasserts the essential CoreDNS placement; CoreDNS
is not a Helm release. Application apply installs the ProxyClass before releases.
The common Talos patch enables kubelet serving-certificate bootstrap on all nodes;
CSR approval remains an explicit node-identity check.

Application, CI-service and Talos apply stages refuse a NotReady or cordoned
primary worker, or a hibernated CNPG database. Complete the laptop wake runbook
and restore its journal before deploying. The two Proxmox roots ignore runtime
`started` drift so infrastructure reconciliation does not undo manual sleep/wake.
This is not automatic power management.

## State reconciliation already performed

The authoritative S3 primary state was backed up privately, and only the retired
VM 100 entry was removed under locking. Worker 01's complete state entry matched
before and after. Refreshed plans against both running hosts have zero VM changes.
Source VM 100 remains
physically preserved, stopped/protected/onboot=0. Do not re-import it or boot its
stale disk. The old checkout's claim that no remote primary state existed was
incorrect and has been corrected in the migration evidence.

Private evidence and backups are under
`~/.local/share/main-control-plane/iac-reconciliation` on the administrator Mac.
They must never be committed. Existing encrypted state backend keys are unchanged.

## Live verification on 2026-09-22

Both workers became Ready during the approved temporary wake. Each refreshed
provider plan contained exactly its existing worker with a `no-op` action.
No provider apply was needed. Primary S3 state and secondary private local state
were reused; no empty state, import or VM recreation was introduced.

Exactly four `/vms/100` ACL entries were removed from the primary plan/apply users
and tokens. All other ACL entries were preserved. Both identities passed the live
HTTPS permission preflight. The check allows the apply identity's inherited
host-level `Sys.Modify` but rejects every VM-specific privilege on the retired VM.
The secondary lock file now includes the signed Linux AMD64 provider checksum.

Primary data-volume identity and all 21 PV / 22 PVC identities, bindings and
affinity remained unchanged. API, etcd, internal DNS and external DNS checks
passed on the laptop. Workloads remained paused and both workers cordoned during
verification; the original `manual-off-20260922-primary` maintenance journal
remains the source for a future workload restore. No scheduled work was resumed.
Both Talos workers were then shut down gracefully. Both IMM controllers confirmed
physical power off, and the laptop API, etcd and internal/external DNS passed again.

## Helm rollout procedure

The independent CI/admission root was subsequently applied through its guarded
saved-plan administrator path during PR 117 verification. Its follow-up plan was
empty and PV/PVC identities and bindings were unchanged. This also corrected the
stale 172-GiB-worker assumption: the primary's reviewed compute pool is now
31.25 CPUs / 84 GiB, with a 6.5-CPU / 24-GiB platform reserve, checked against
observed allocatable capacity. Dormant AI requests and data remain unchanged.
The Talos and application release rollout below still uses the `apply` label.

These steps require an explicitly approved temporary host wake:

1. Wake through IMM using the manual runbook. Confirm source VM 100 remains off.
2. Restore the latest maintenance journal, verifying the worker's original data
   mount and PV/PVC bindings before restoring application writes. Preserve the
   secondary worker's original cordon.
3. Re-run `proxmox-ci-check.py` for plan/apply identities; retired VM ACL removal
   is already complete.
4. Repeat refreshed provider plans with existing states if infrastructure changes
   before rollout. Reject recreation, deletion,
   replacement, or unexplained hardware/storage changes. Do not create empty state.
5. Use the existing saved-plan CI workflow to record the placement renderer in Helm
   release histories. Do not bypass credentials, plan review, or image checks.
6. Verify ready workloads, essential placement, unchanged storage and empty follow-up
   plans; gracefully return both physical hosts to off if that remains the operator intent.

A configuration change is deployed only after the guarded apply and acceptance
checks pass; successful rendering alone does not update Helm release metadata.
The CI/admission root additionally requires an empty follow-up plan. Argo CD has
no Applications or repository credentials and does not own these releases.
Monitoring and GitOps pause while primary sleeps.
