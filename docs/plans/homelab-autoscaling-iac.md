# Homelab autoscaling through OpenTofu and Helm

Status: technical design, 2026-09-20. No deployment or production ownership transfer is performed by this plan. User decisions supersede the earlier retained-worker research recommendation. Ordinary scaling validation is in scope; restore/failure drills and redundancy remain deferred.

## Evidence and immediate next step

The isolated same-host retained-volume proof passed in [issue105](https://github.com/TusharSariyaOrg/aws-account-infra/issues/105): old worker and OS disks deleted, fresh node identity created, original PVC/PV/backend handle and marker verified. This used a manual harness and ISO installation, not the future autoscaler or template clone path.

[IMM2 key access and startup](imm2-power-control.md) are verified. The [power adapter](../../controllers/homelab-capacity/README.md) now uses pyghmi1.6.19 for structured IPMI status and idempotent wake, live-tested from the laptop against both controllers with a dedicated power-only account. Paramiko4 is an optional tested SSH transport; Paramiko5 is incompatible with the current legacy RSA signatures. One isolated zero-to-one worker integration is being validated before expanding to both slots.

## Target

The Ubuntu laptop stays on and hosts the Talos control-plane VM, household DNS and management/demand components. Each physical PVE host supplies at most one main Talos worker VM. That VM is created from a local versioned template on demand and deleted when its capacity is no longer needed. There is no bootstrap management VM. Workloads share the worker; CI runner Pods remain disposable.

Workers have fixed sizes using most of each host's measured capacity with a Proxmox reserve. Existing 38-vCPU/112-GiB worker allocations are a reference, not a new entitlement: reconcile CPU overcommit, actual usable memory and host services before declaring template allocatable values. Templates and retained data consume storage; thin allocation does not make scratch unlimited.

Use awake eligible capacity first. Additional runnable demand that cannot fit initiates capacity creation without a predictive queue delay. Do not create a VM for every queued item. A workload exceeding every worker's capacity or violating placement constraints remains visibly unschedulable rather than repeatedly waking hosts.

One 30-minute idle window governs an unneeded worker and its physical host. Do not stack separate VM and host cooldowns. A vanished request during boot need not abort provisioning; the now-unneeded capacity may finish starting and enter the same idle policy. Per-app permission is authoritative for movement, restart, active sessions and job completion. A persistent workload or other host dependency can keep a server on.

## Ownership: exactly one reconciler per resource

| Resource | Desired-state owner | Runtime owner |
| --- | --- | --- |
| PVE endpoint inventory, template definitions, bridges, host storage configuration and API permissions | OpenTofu, using separate endpoint configurations | Proxmox |
| Laptop management VM and stable host services | Appropriate existing IaC/configuration mechanism, with bootstrap independent of this cluster | Ubuntu/service manager; never the worker autoscaler |
| Helm releases, namespaces, RBAC, controller limits, node-group configuration and app policies | OpenTofu Helm provider / versioned Helm values | Respective controllers |
| Disposable worker VM instances, identities and node membership | Autoscaler group/template specification | Selected provisioning adapter/provider |
| Pod placement and workload admission | Helm policy/resources | kube-scheduler and Kueue |
| App PVCs, storage classes, retention and topology policies | App/platform Helm charts | Selected storage controller and attachment controller |
| Physical host desired power and in-flight operation state | Versioned lifecycle policy | One laptop-hosted power coordinator |

OpenTofu must not declare each autoscaled VM as a permanent resource. Conversely, the controller must not touch current OpenTofu-managed production VMs, templates, laptop resources or durable storage outside its ownership. `ignore_changes` on VM power is not an ownership transfer. State reconciliation is a deliberate migration step, not an automatic destroy/apply cycle.

Declarative IaC installs and configures the system; it is not repeatedly applied to react to each queue event. Custom controller code, if required, is versioned, packaged as an image and deployed through Helm with explicit resource limits. This is not a claim that every Ubuntu host setting has a native Terraform resource.

## Component boundaries

- ARC controller/listeners stay on management capacity, even with zero runners. Scheduled and app-invocation demand must also remain observable with zero workers.
- Kueue manages admission and approved quota. Its capacity-request integration must see scheduling-gated work, rather than relying exclusively on unschedulable Pods.
- Cluster Autoscaler simulates fit and requests group capacity. Model primary and secondary as distinct groups, each minimum zero and maximum one, with accurate labels, taints and allocatable templates.
- kube-scheduler packs eligible workloads by requested resources. Actual CPU utilization alone is not an admission budget or an app-idleness signal.
- App policy translates scheduled/on-invoke/persistent/experimental behavior into demand and eviction constraints. The infrastructure controller does not invent a separate application dependency graph.
- The power/provisioning layer resolves each physical host by endpoint plus node name, not by the non-unique string `pve`. It reconciles asynchronous PVE/IMM2 operations and excludes unmanaged guests/services from deletion.

Provider recommendation for the first prototype: upstream CA with an external gRPC adapter that maps the two fixed worker slots to their independent PVE endpoints and IMM2 controllers. This accommodates the existing topology without introducing Cluster API control-plane ownership. Keep CA+CAPI+CAPMOX as an alternative only if it supports the two independent endpoints and worker-only integration without forcing a PVE cluster migration or replacing the laptop control plane. The final provider contract remains a proof gate, not a settled release selection. Do not run two autoscalers against the same workers.

## Applying IaC while servers sleep

Separate laptop/Helm management stacks from PVE host/template stacks so an ordinary management change does not require refreshing both sleeping PVE APIs. A PVE-targeted plan/apply first registers an explicit maintenance demand, wakes only its required host and holds it awake until the operation ends. The same per-host coordination prevents autoscaler deletion or physical shutdown during that operation. Do not interpret a refresh timeout as permission to recreate resources, and do not routinely disable refresh to hide unavailable hosts.

Templates, controller images and bootstrap inputs must be available without a dependency on an execution host that is off. Each eligible PVE host has its local versioned template. The laptop owns wake access. IaC configures credential references and permissions; ephemeral worker configuration and private keys are not committed to manifests or printed in job output.

## Normal lifecycle

1. Demand identifies requested resources and eligibility. Quota represents approved attainable capacity; powered-off capacity is not automatically zero entitlement.
2. Prefer capacity that is already awake and eligible. If additional capacity is necessary, request one eligible zero-to-one group transition.
3. The power coordinator turns on the physical host through its supported IMM2 interface and waits for PVE API readiness. Report pending progress; do not block short provider RPCs for the whole boot.
4. Clone the host-local template into an explicitly owned VM ID/name. Generate new worker identity and Talos configuration for the existing cluster. Templates contain no copied production node identity. Wait for actual node readiness, networking and required storage attachment; accepted provisioning is not application readiness.
5. Admit/schedule work with its CPU, RAM, scratch and placement requirements. Browser app wakes use the waiting page; API callers receive503/Retry-After without automatic replay of mutating requests.
6. When demand can fit on fewer hosts, prevent new assignments to the candidate being emptied and move only workloads whose app policy permits it. Finish active CI/jobs; respect volume locality. Experimental work does not itself keep a host alive and receives graceful termination.
7. After the shared idle window and a final demand/blocker check, complete drain and clean guest shutdown. A per-host reconciliation lock prevents duplicate creates/deletes; reconcile actual state after restarts.
8. Detach and verify release of every durable volume through its supported lifecycle. Delete only owned disposable OS/scratch resources and the obsolete Kubernetes node identity. A storage release failure blocks deletion; it never becomes permission to discard data.
9. If no other host workload requires power, request orderly PVE shutdown and verify off using IMM2. Do not substitute an IMM2 forced timeout for successful drain. New demand before shutdown commit cancels shutdown; afterwards it remains queued until the host can be started again.

Host shutdown must preserve the selected API/DNS/wake paths on the laptop. Stable routes and capability labels replace fixed worker hostnames where portable. Storage-bound apps retain the physical storage-domain constraint.

## Storage contract

The user accepts durable data bound to one physical server, provided a replacement worker can reattach it. This avoids requiring distributed storage and does not promise availability while that server sleeps.

Current local-path volumes and cache PVs are pinned to talos-worker-01. Its1200-GiB data disk is part of the existing guest definition. Keeping a Kubernetes PV or setting `Retain` alone does not prove the PVE VM deletion path preserves its underlying disk. Treat the existing guest/disk as protected until migration to a proven independent volume lifecycle is complete.

Proxmox CSI0.20.0 (chart0.5.12) passed the ordinary retained-volume lifecycle on standalone secondary PVE9.2.2 with Talos1.13.9, verified TLS, local thin storage and separate owner ID9199. No PVE cluster conversion was needed for that tested path. Validate primary-host topology and the actual controller deletion path before migrating apps; the manual proof does not cover those integrations. Inspect both attached and unused disk references before VM destruction. See [storage evidence](../../prototypes/disposable-worker-storage/evidence.md).

Use separate ownership manifests for disposable guest disks and durable volume IDs. Single-writer attachment must be enforced across old/new worker identities. Attach completion and the expected filesystem/data must be verified before scheduling stateful apps. Node labels describe physical storage domains; fresh Kubernetes node names must not strand local PV affinity. Existing local-path data may require migration to a new volume; this is normal storage migration, not a deferred recovery exercise.

## Repository changes to implement later

- `live/proxmox/homelab` and `homelab-secondary`: retain durable foundations and templates; current fixed guest resources have `prevent_destroy` and must remain protected until a reviewed ownership/migration plan.
- `live/talos/homelab`: retain control-plane ownership; fixed worker configuration resources must not race runtime provisioning. Preserve cluster identity while issuing per-worker configuration.
- `live/kubernetes/homelab-ci`, ARC values and Kueue ResourceFlavor: move management components to the laptop, remove worker01-only selectors for portable jobs, introduce two-group capacity integration.
- Capacity validation: replace assumptions that worker01 must always be Ready and supply fresh filesystem statistics before a wake. Separate attainable capacity checks from post-wake measured storage/admission checks. Preserve the separately proposed80-GiB current-worker RAM correction; do not resurrect the obsolete144-GiB quota while changing topology.
- Storage/app charts: replace fixed worker identity with validated volume topology/attachment. Encode movement and runtime policy per app.
- New Helm release(s): selected autoscaler/provider and power/app-policy integration, with explicit credentials boundaries and controller ownership labels.

## Ordered implementation gates

1. Pin the chosen provider/CA/Kueue/CSI versions and define their contracts. Render Helm and validate IaC without live changes. Account for the full controller footprint on the laptop.
2. In the isolated prototype, prove a Kueue-gated request at zero workers causes one correct create/join operation. Confirm readiness rather than only successful API submission. Also cover ordinary non-Kueue workload demand.
3. Write a marker to a disposable durable volume, remove the worker VM and its disposable disks through the intended controller, create a different worker identity on that host, then reattach and read the marker. Explicitly verify backend volume survival and exclusive attachment.
4. Prove app-permitted consolidation, job protection, both half-loaded hosts converging onto one when feasible, shutdown cancellation before commit, and one30-minute timer. No forced removal when the app/storage policy blocks movement.
5. Review migration changes together: always-on placement, hostname/topology rules, existing data, OpenTofu state ownership and worker enrollment. Existing production VMs remain outside autoscaler ownership until this reviewed transition.
6. Implement in phases with ordinary readiness checks. No production apply, host power action or existing VM deletion is authorized merely by writing this plan.

## Outstanding technical evidence

The [one-slot prototype](../../prototypes/one-slot-autoscaler/evidence.md) proves external-gRPC scale-up and fresh Talos enrollment for an ordinary Job on the secondary endpoint. Kueue admission, cold physical wake and two-endpoint integration remain unproven; retained-volume lifecycle through the actual runtime controller on both hosts; measured laptop controller footprint; exact worker budgets and node-template resources. These are implementation-fit questions, not new user preference questions. Backup/restore, redundancy and hardware-failure drills remain deferred.

Primary-source provider and storage findings: [autoscaling research](../research/homelab-power-autoscaling.md), copied from research commit7207381.

## Build sequence and acceptance

1. **Power adapter:** strict host trust, separate laptop credential, observed-state parsing, idempotent wake and bounded errors. No forced-off path.
2. **Worker provisioning:** versioned local templates, fresh Talos identity, two distinct endpoint/slot identities, exclusive ownership, retain/detach checks before deletion. Prove one isolated slot first.
3. **Demand and admission:** Kueue-gated jobs and ordinary pending work request capacity through CA external gRPC. ARC listeners remain on always-on capacity. Fit includes CPU, RAM, scratch and storage locality; correct current RAM budgets.
4. **App wake policies:** every app declares scheduled, on-invoke or persistent; unclassified experimental work is gracefully disposable. LAN/Tailscale URL wakes show a waiting page; APIs return503/Retry-After, without replaying mutations. Scheduled work declares its deadline or awake-window deferral policy.
5. **Consolidation and sleep:** prefer awake eligible capacity, respect per-app movement/completion and host blockers, one30-minute idle timer, cancellation before shutdown commit and queued re-wake afterwards. Demonstrate feasible consolidation across both slots.
6. **IaC and migration:** OpenTofu owns stable infrastructure/templates/permissions; Helm deploys versioned controllers and policy. Runtime owns disposable workers. Move essential DNS/management to laptop capacity, migrate protected storage explicitly, then transfer worker ownership in reviewed phases.

GitHub remains the execution tracker, principally [placement97](https://github.com/TusharSariyaOrg/aws-account-infra/issues/97), [admission100](https://github.com/TusharSariyaOrg/aws-account-infra/issues/100), and [migration99](https://github.com/TusharSariyaOrg/aws-account-infra/issues/99). These documents hold the detailed contract and evidence; no backup/restore drill or redundancy prerequisite is added.
