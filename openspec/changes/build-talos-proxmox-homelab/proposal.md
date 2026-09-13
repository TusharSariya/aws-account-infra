## Why

The Talos homelab architecture in PR #31 needs to move from a proposed design to a controlled, recoverable Proxmox deployment. The build includes manual host and VM operations, so each action and its evidence must be captured in Git without recording secrets.

## What Changes

- Acquire and verify pinned Talos installation artifacts (the previously acquired Debian ISO is retained as unused history).
- Inspect and prepare the Proxmox host before allocating guest storage or creating VMs.
- Support private remote administration through Tailscale installed on the Proxmox host, with verified access policy, optional-to-activate planned subnet routing, local fallback and reproducible enrollment/recovery inputs.
- Create two Talos VMs: a 2-vCPU/4-GiB control plane and a 38-vCPU/172-GiB shared worker, with 100-GiB OS disks and a separate 1,200-GiB worker data disk.
- Install the QEMU guest agent extension on every Talos VM and the gVisor extension only on the shared worker.
- Bootstrap and verify the Talos Kubernetes cluster, then configure worker-local persistent storage and backups in later implementation phases.
- Maintain a timestamped, append-only implementation log containing actions, results, evidence references, deviations, and rollback information while excluding secrets.
- Make every completed operation recoverable from versioned desired state or an exact manual rebuild procedure, with independently recoverable secrets and off-site recovery material; include the laptop network and administrator access in the recovery scope.
- Prove full-platform recovery from a clean administration environment in an isolated rehearsal, recording recovery time and data-loss bounds.
- Gate destructive, security-sensitive, and live infrastructure actions on explicit checks and record their outcomes before marking tasks complete.

The 2026-09-12 operator revision removes the dedicated NAS and sandbox VMs. Trusted services and sandbox workloads share the worker; gVisor, admission controls and network policies remain required for sandbox pods. Dedicated VM, physical-core and NUMA trust isolation are no longer claimed.

## Capabilities

### New Capabilities

- `homelab-provisioning`: Defines the reproducible and auditable provisioning, validation, and recovery requirements for the Proxmox-hosted Talos cluster and worker-local storage.

### Modified Capabilities

None.

## Impact

- Affected systems: the IBM System x3550 M4 Proxmox host, its ServeRAID-backed LVM-thin pool, the trusted LAN, two Talos VMs.
- Affected repository areas: OpenSpec change artifacts, Proxmox and Talos configuration, infrastructure automation added during implementation, and the existing homelab plans in `docs/plans/`.
- New external artifacts: two Talos v1.13.9 Image Factory schematics and ISOs, their matching installer image references, and immutable installer digests.
- Operational risk: the host has one physical failure domain and an aging disk array; important state must remain recoverable off-host.
- No live infrastructure mutation is authorized by this proposal alone. Execution begins only through the OpenSpec apply workflow and operator-approved manual steps.

The 2026-09-13 backup revision adds daily GitHub-operated etcd snapshots, public-key encryption, dedicated AWS OIDC upload/readback permissions, independent missing-backup monitoring and 30-day noncurrent-version retention while keeping the latest daily backup indefinitely.


The operator-approved automation simplification revision reduces custom Python
orchestration before adding further platform features. Keep OpenTofu, Helm and
GitHub Actions; use native blocking validation and visible workflow steps where
they replace custom logic. Retain focused helpers for private Talos identity
handling, live disk safety and verified encrypted backups. Separate deployment
from integration tests and explicitly invoked recovery/reboot rehearsals. This
revision plans a behavior-preserving refactor, not an infrastructure migration.
