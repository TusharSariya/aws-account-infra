## Why

AI services currently reserve resources continuously and use shared local-path storage without hard per-volume write boundaries. Multiple applications need a reproducible private job scheduler and safe service lifecycle controls.

## What Changes

- Install pinned Argo Workflows through existing OpenTofu/Helm CI, exposing authenticated private Tailscale UI/API and reusable manual, API and scheduled jobs.
- Add Start AI, Stop AI, Force Stop AI and Status operations with durable controller-owned state, graceful draining and shutdown after 30 minutes of verified inactivity.
- **BREAKING**: migrate the four AI services into one Pod, initially off, reserving 35.75 CPU and 77 GiB RAM; Ollama reserves 34 CPU and 64 GiB. Preserve VM CPU/RAM and independent Pi-hole operation.
- Enforce shared-XFS project-quota AI storage boundaries, retained static volumes, bounded temporary storage and fail-closed guest/physical capacity checks. Reset only models, workspace and vector application data.
- Reconcile deployment evidence, preserving unverified benchmarks, interaction and recovery tests.

## Capabilities

### New Capabilities

- `homelab-workload-scheduling`: authenticated jobs and service lifecycle controls, aggregate scheduling and fail-closed activity handling.

### Modified Capabilities

- `odysseus-workspace`: on-demand operation and aggregate resource reservation, initially off.
- `homelab-provisioning`: enforced AI storage boundaries and physical capacity accounting.

These two capabilities currently exist in active changes, not archived main specs. Add their new requirements to their originating change files; do not invent MODIFIED deltas against nonexistent main specs or archive incomplete recovery work.

## Impact

Talos quota configuration and existing Proxmox disk safeguards, application Helm releases, deployment health checks, private credentials, lifecycle instrumentation and job acceptance. Deliver storage foundation, AI packaging/resource controls, then scheduler/lifecycle integration in dependency order. Queue autoscaling and advanced fairness remain deferred.
