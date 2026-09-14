# Implementation evidence

## Local checks, 2026-09-14

- Planning artifacts and both affected active specifications pass strict OpenSpec validation.
- 94 local unit/contract tests pass across `scripts/tests`; Helm renders are included.
- Talos and Kubernetes OpenTofu roots initialized backend-free with read-only lockfiles and passed validation. Backend keys and pinned provider versions were not changed.
- ShellCheck and actionlint pass for the changed scripts/workflows.
- Trivy HIGH/CRITICAL configuration scan passed. Checkov reports 663 passed, 0 failed and 87 existing skips. TFLint recursive scan passed.
- Gitleaks baseline history scan reports no leaks. Rescan staged/new content before publishing.
- Disposable Linux XFS testing passed quota write rejection with confirmed physical headroom, neighboring writes, overcommitted declarations, UUID retrieval, quota/project persistence across unmount/remount, rejection of missing mounts/wrong devices/disabled quotas, and project-zero escape rejection inside a user namespace.

## Findings

- The initially tested ordinary non-root file owner could change an owned file's project ID to zero without quota-administration capabilities. Consequently, migrated application consumers must use `hostUsers: false`; worker user-namespace prerequisites and an adversarial regression test were added. Linux-container testing is not live Talos/Kubernetes acceptance.
- `lvs --readonly` omits live device-mapper state. The sampler instead uses only the fixed `lvs` reporting command with explicit fields and never accepts command arguments from clients.
- An existing local Proxmox SSH identity can query physical capacity. A read-only sample observed `pve/data` at 1.71% data and 0.20% metadata. This is a point-in-time administrative query, not independent collector deployment evidence.
- The local kubeconfig points to an older, unresolved desktop endpoint. No attempt was made to replace it or bypass the protected Talos CI identity.

## Outstanding gates

The new capacity release is disabled pending trusted filesystem UUID enrollment, independent collector credential provisioning, endpoint routing verification and live quota maintenance acceptance. The root host installation recipe is repository managed but has not been run. No production apply, quota activation, worker reboot, reset, migration, model benchmark or restore is claimed for this change.

Storage review/CI rollout must precede AI packaging and lifecycle/Argo rollout. The task checklist remains authoritative and unfinished work is not archived.
