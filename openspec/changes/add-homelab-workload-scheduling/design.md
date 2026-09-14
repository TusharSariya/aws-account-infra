## Context

See proposal.md for motivation. The existing worker data disk is 1200 GiB, with a 1199 GiB XFS user partition mounted at `/var/mnt/local-path-provisioner`. Existing local-path claims, including Pi-hole, must survive this change. VM hardware and OpenTofu backend keys remain unchanged. Deployment already runs Proxmox, Talos and Kubernetes in order using guarded saved plans, private Tailscale access and protected CI credentials.

## Goals / Non-Goals

Make quota enforcement, physical capacity, atomic AI scheduling, admission, activity and lifecycle state reproducible. Keep application data recovery independent of configuration reconstruction. Do not introduce queue autoscaling, advanced fairness, additional disks or automatic data deletion.

## Decisions

### Ownership and storage

Proxmox owns existing hardware. Talos owns `UserVolumeConfig.filesystem.projectQuotaSupport: true`. Kubernetes OpenTofu owns Helm releases for platform helpers, static retained volumes, application templates and policies. The local-path provisioner remains intact for unrelated claims. Administrative PVC request quotas are not physical reservations.

Use directories `ai-models`, `ai-workspace` and `ai-vector` under the existing mount, project IDs 31001, 31002 and 31003, and initial hard limits 300, 20 and 10 GiB. Limits may sum above filesystem capacity. They neither allocate blocks nor promise available space. Retained static local PVs bind explicitly to those directories and worker hostname. The helper rejects missing mounts, unexpected filesystem identity, symlinks, disabled enforcement and incorrect project inheritance. It has no user-supplied command API. Only the helper may administer quotas; applications receive only their own PVCs and MUST run with `hostUsers: false`. A disposable Linux test proved that an ordinary non-root file owner in the initial user namespace can use FSSETXATTR to move its file to project zero. Root ownership of the directory and dropped capabilities do not prevent that escape. Kubernetes user namespaces block project-ID changes; Talos enables the worker-only `user.max_user_namespaces: "11255"` prerequisite. Require adversarial project-zero rejection in both isolated Linux and live Pod acceptance before migration. Preserve RuntimeDefault seccomp and dropped capabilities.

Talos documents that enabling project quotas may require a full remount. Keep ordinary application of configuration in no-reboot mode and verify activation through explicit worker maintenance. Do not reformat, wipe or grow the disk. An isolated disposable small-volume test must prove quota rejection on one project with verified physical headroom while a neighboring project remains writable; reporting accounting as enabled is insufficient.

### Capacity and pressure

Collect guest space/inodes and project usage every 30 seconds. Independently collect physical Proxmox thin-pool data and metadata through a read-only host recipe, separate credential and fixed command. Do not substitute guest allocation or Proxmox storage free bytes for thin-pool metadata. Pin the expected filesystem and pool identities in reviewed configuration.

Startup and work admission require all expected measurements to be healthy and at most 90 seconds old. Future timestamps and invalid/nonfinite percentages are unhealthy. Warn at 80 percent; at 90 percent latch pressure, close admission and gracefully drain. Missing or unhealthy telemetry closes admission as well. Clear a latched pressure condition only after five continuous minutes with every required metric below 80 percent; missing samples or controller restart break continuity. Clearing pressure never starts a drained stack. No pressure path deletes data or invokes Force Stop.

### Runtime and activity

One runtime Deployment contains Ollama, Odysseus, Chroma and Searx with CPU/memory requests equal to limits: 34/64Gi, 1/8Gi, 500m/4Gi and 250m/1Gi. Bound disk-backed emptyDirs and per-container ephemeral storage independently. EmptyDir size limits and ephemeral-storage limits are kubelet eviction controls, not synchronous XFS hard limits.

Helm owns an approved Pod-template ConfigMap and controller configuration. The lifecycle controller creates and owns the Deployment and its replica count. Persist desired state and monotonically increasing command revision in Kubernetes using resourceVersion compare-and-swap; use a Lease for leader election and recheck the current revision before reconciling. Start reports Starting or Pending until ready; Stop supersedes pending Start. Default state is off. Normal Stop closes admission and waits for every instrumented source to confirm completion. Force Stop records interruptions, requests bounded termination and reports completion only after Pods disappear.

Instrument the pinned Odysseus source around streams, document processing, agents, scheduled executions and subprocess lifetime, including exceptions/cancellation. Track direct inference and model downloads through an authenticated admission gateway. Prevent both network and same-Pod bypass of the gateway; a NetworkPolicy alone cannot isolate containers sharing localhost. Tokens for already admitted work may continue during draining; new work is rejected or deferred. Unknown activity blocks drain completion and resets the idle interval. Health probes and idle browser connections are excluded. Thirty continuous verified idle minutes trigger normal Stop; controller recovery starts a new interval.

### Argo and private access

Install an immutable checksum-verified Argo chart through the existing Helm provider. Expose private Tailscale HTTPS with client-token authentication and namespace-scoped RBAC. Restrict workflows to reviewed WorkflowTemplates and approved service accounts; ordinary jobs cannot access controller credentials, host storage or quota privileges. Lifecycle operations use a separate authenticated API credential. Scheduled jobs use UTC, Forbid overlap and a per-job mutex shared with manual/API invocation. Independent jobs may run together when resources fit. Include an initially suspended smoke CronWorkflow.

## Migration Plan

1. Storage foundation PR: complete and strictly validate OpenSpec, reconcile historical CI evidence, add quota prerequisites/helper, independent capacity collection and isolated acceptance. Keep current workload ownership and disks intact. Explicit maintenance verifies quota activation and persistence.
2. AI packaging PR: stop all identified AI writers, verify Pod termination and exact PVC/PV UIDs and paths, then execute a uniquely identified, durable one-time reset of only the three authorized AI application volumes. Routine CI cannot invoke or replay the reset. Install retained static claims and the approved aggregate template, default off. Keep the old releases at zero and preserve unrelated resources. Add only precisely enumerated migration plan allowances.
3. Lifecycle/Argo PR: deploy controller, gateway and complete pinned activity instrumentation. Keep runtime off until an explicit authenticated Start. Exercise command races, recovery, idle timing, draining, pending scheduling, cancellation and private access in explicit acceptance jobs.

Each PR must pass strict OpenSpec validation, relevant local checks, guarded plan/apply and all selected acceptance before merge. Failures, cancellations and unexpected skips fail the merge gate. Chart, code, image, configuration and test changes must select their checks. Review gates and apply label remain intact.

Configuration rollback cannot recover erased application data. Record failed attempts and successful deployments separately from live behavior, benchmarks and isolated restore evidence. Do not archive unfinished work.

## Risks / Trade-offs

- Storage overcommit can exhaust the shared filesystem between samples. Admission and drain reduce risk but cannot guarantee an active operation has enough space.
- Unknown activity can leave graceful shutdown waiting indefinitely. Report the blocker; only an explicit Force Stop may interrupt it.
- Enabling quotas may require worker reboot and temporarily interrupt worker workloads. Use the existing explicit maintenance gate and verify Pi-hole afterward.
- A quota administrator necessarily has elevated filesystem authority. Keep it in a separate platform namespace with fixed inputs, no external command interface and no application credentials.
- Shared Pod localhost permits container-to-container access. Gateway enforcement must cover that path before claiming complete activity accounting.

## References

- [Talos 1.13 UserVolumeConfig](https://docs.siderolabs.com/talos/v1.13/reference/configuration/block/uservolumeconfig): projectQuotaSupport and remount requirement.
- [Linux XFS documentation](https://www.kernel.org/doc/html/latest/admin-guide/xfs.html): project quota accounting versus enforcement.

- [Kubernetes project-quota reliability and user namespaces](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/).
- [Talos user-namespace prerequisite](https://docs.siderolabs.com/kubernetes-guides/security/usernamespace).
