## Context
The approved migration replaces VM 103 with trusted ARC Docker-in-Docker Pods on Talos. Historical VM implementation and failed attempts remain evidence, not migration acceptance.

## Goals / Non-Goals
Kueue reserves declared requests. Kubernetes schedules and enforces limits. The lifecycle controller owns AI desired state, replicas, draining, activity, idle shutdown and storage-pressure protections. ARC owns disposable runners; Argo owns workflow execution. DNS, networking, storage helpers, platform controllers and operational commands stay outside admission.

## Decisions
Install Kueue 0.19.4 and ARC 0.14.2 with OpenTofu-managed Helm in an independent Kubernetes CI root. Use one worker-bound ClusterQueue, StrictFIFO, equal priority, no preemption, no cohort/borrowing/fairness and 36 CPU / 160 GiB quota. Namespace LocalQueues are submission points, not reserved partitions. Concurrent reservations must fit; an older waiting large workload blocks a newer smaller one. Reject requests larger than the pool with an actionable message. FIFO starts at Kueue submission, not at GitHub's upstream queue.

AI keeps its aggregate 35.75 CPU / 77 GiB reservation and retained volumes. Use Deployment/Pod integration without transferring lifecycle ownership. Start queues; Stop cancels waiting work or drains running work; Force Stop keeps explicit semantics. Queue waiting cannot accrue idle time. Adopt runtime templates only while off, avoiding two AI reservations. Status adds queue order, resources and blocking reasons without replacing existing API states. Release reservations only after observed termination.

ARC uses separate controller/runner namespaces and the existing repository-scoped GitHub App via a privately enrolled Secret. minRunners=0 with no ARC maximum. Kueue controls admitted concurrency across a repository-managed catalog of arbitrary reviewed CPU/RAM/scratch budgets, with one homogeneous scale set per configuration. Catalog CPU uses cores (whole millicores); memory/scratch use MiB. `homelab-talos` remains 4 CPU / 16 GiB / 30 GiB with Docker; `homelab-talos-light` starts at 1 CPU / 2 GiB / 2 GiB without Docker, and `homelab-talos-checks` at 2 CPU / 4 GiB / 4 GiB without Docker. These are initial job budgets, not universal minimums or fixed tiers. Promote jobs only through reviewed catalog changes deployed before workflow references. OpenTofu generates container budgets; actual rendered effective Pod requests and matching limits must equal the catalog, including restartable Docker and initialization peaks. Preserve the existing release with an OpenTofu moved block and wait for existing runners to become idle before updating it. No host filesystem or host Docker socket mounts. Fork execution is disabled. Preserve ARM artifacts via tested ARM packaging. Verify cancelled/expired GitHub work deletes pending runner workloads.

Argo ordinary execution Pods use plain-Pod admission. Preserve reviewed templates, UTC schedules, Forbid overlap and mutexes. Queue waiting is separate from execution deadlines. Start/Stop/Force Stop/Status Pods bypass Kueue. Admission filtering must allow platform/operations when Kueue is unavailable and prevent compute bypass.

## Migration Plan
PR 1: foundation, independent hosted/Mac bootstrap and recovery, budgets and narrowly guarded retirement of VM 103. Remove only its DHCP reservation and dedicated permissions, retain GitHub App/key. Gracefully restore worker RAM to 172 GiB. Verify node allocatable covers platform reservations plus the pool and verify Pi-hole before activation.
PR 2: pinned Kueue/ARC Helm, admission enforcement, AI/Argo integration, private enrollment and status.
PR 3: CI_EXECUTOR routing, ARM path, acceptance and operations. Default to github-hosted until observed acceptance; never introduce automatic fallback. Hosted bootstrap/upgrades/recovery retain existing OIDC, Tailscale, saved-plan checks and approvals. Keep Mac bootstrap because hosted allowance was exhausted.
Keep AI off throughout migration. Preserve existing state keys and append evidence, including failures. Never credit local checks as successful GitHub checks.

## Risks / Trade-offs
The single worker remains a shared failure domain. Trusted privileged Docker runners are not isolation for hostile fork code. StrictFIFO may leave resources unused while the head waits. Per-Pod Argo admission is not atomic workflow admission. Controller failure must not strand operational commands.

## Validation
Verify pinned artifacts, rendered Helm, OpenTofu plans, workflow contracts, admission/security policies and strict OpenSpec. Exercise AI-first/CI-first contention, FIFO head blocking, CPU/RAM exhaustion, cancellation, expiry, controller/node restart and reservation cleanup. Prove Stop/Status and Pi-hole during exhaustion and Kueue outage. Run actual ARC checkout/build/ARM/private deployment/quota jobs and hosted recovery with ARC absent. Require fresh empty post-deployment plans and existing merge gates; leave unobserved acceptance unchecked.

## Observed capacity adjustment, 2026-09-15
The restored 172-GiB guest exposes 168.44 GiB allocatable. The user approved an 8-GiB platform reserve after observing 1.81 GiB Pod working set and 448 MiB additional controller requests, preserving the 160-GiB pool and 172-GiB worker. Admission still requires the complete pool plus reserve to fit observed allocatable.

## Shared scratch and job-sized rollout
The shared ClusterQueue also admits ephemeral-storage against 60 GiB, without
separate runner partitions or borrowing. Scratch includes logs, writable layers
and bounded emptyDir volumes. Retained AI PVC storage is never used as compute
scratch. AI keeps 35.75 CPU / 77 GiB; it still prevents a 1-CPU runner from fitting.

At plan and apply, fresh kubelet root/image measurements plus the full scratch
quota and 8 GiB additional storage headroom must fit node allocatable and measured
free bytes. Missing, stale or insufficient measurements fail deployment. Node
allocatable already excludes kubelet eviction reservations. Root use includes
images on Talos; check root and image filesystems independently without adding
image bytes twice. Recheck all desired listener reservations, available Pod slots
and 10 additional platform/Argo slots. Keep the 8-GiB platform RAM reserve.

Audit every routine job, including reusable storage/acceptance and supporting
gates. Select lightweight, checks or Docker-enabled configurations explicitly;
install only requested prerequisites. Bootstrap, admission upgrades, physical
maintenance, independent backups and recovery retain hosted execution and Mac
fallback. Workflow-only changes must not fan out to unrelated state roots.

Deploy admission/catalog first, run explicit Talos proofs including simultaneous
mixed sizes, combined CPU/RAM/storage exhaustion and cleanup, then merge validated
routing and set CI_EXECUTOR=talos. Observe GitHub's documented 24-hour queue expiry
separately from cancellation with external monitoring and fixture cleanup. Keep
unobserved acceptance unchecked. Verify actual routine runs, empty plans,
autostart, Pi-hole and AI Off before returning the temporary Actions budget to $0.
