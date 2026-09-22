# Main-cluster IaC ownership

Configuration reconciliation is on `fix/main-cluster-iac-reconciliation`, based on
current main, rather than the stale `docs/talos-homelab-plans` checkout used during
migration. Both physical application hosts remain intentionally off. Live Helm
upgrades and refreshed Proxmox plans have not been run during this reconciliation.

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
before and after. A state-based plan has zero VM changes. Source VM 100 remains
physically preserved, stopped/protected/onboot=0. Do not re-import it or boot its
stale disk. The old checkout's claim that no remote primary state existed was
incorrect and has been corrected in the migration evidence.

Private evidence and backups are under
`~/.local/share/main-control-plane/iac-reconciliation` on the administrator Mac.
They must never be committed. Existing encrypted state backend keys are unchanged.

## Remaining live rollout

These steps require an explicitly approved temporary host wake:

1. Wake through IMM using the manual runbook. Confirm source VM 100 remains off.
2. Restore the latest maintenance journal, verifying the worker's original data
   mount and PV/PVC bindings before restoring application writes. Preserve the
   secondary worker's original cordon.
3. Remove the retired `/vms/100` ACLs from both existing CI users/tokens, preserving
   worker/storage permissions. Re-run `proxmox-ci-check.py` for plan/apply identities.
4. Run refreshed provider plans with existing states. Reject recreation, deletion,
   replacement, or unexplained hardware/storage changes. Do not create empty state.
5. Use the existing saved-plan CI workflow to record the placement renderer in Helm
   release histories. Do not bypass credentials, plan review, or image checks.
6. Verify ready workloads, essential placement, unchanged storage and empty follow-up
   plans; gracefully return both physical hosts to off if that remains the operator intent.

Until that rollout, live placement remains the already-tested migration placement;
new Terraform/Helm configuration describes it, but has not been applied to release
metadata. Argo CD still has no Applications or repository credentials and does not
own these releases. Monitoring and GitOps pause while primary sleeps.
