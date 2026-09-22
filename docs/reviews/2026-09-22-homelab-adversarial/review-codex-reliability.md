> Raw agent report from the 2026-09-22 homelab adversarial review. It was produced against a local working tree behind `main`; several findings were fixed on `main` (`000bb81`) before filing. See [README.md](README.md) for the re-verified status and issue links.

**Verdict:** a carefully operated, recoverable-in-place homelab, but not yet a production-like platform for arbitrary workloads.

This was a read-only repository review. Recorded live acceptance is credited; I did not independently inspect the cluster or private backup contents.

**Goals 1–5**

1. **PARTIAL:** Private applications have recorded acceptance; the proposed public-ingress design does not establish operational readiness.
2. **PARTIAL:** Compute placement exists, but current evidence preserves dormant AI workloads rather than proving scheduled, on-demand, and persistent GPU operation.
3. **PARTIAL:** Isolation and resource safeguards exist; availability and latency guarantees across host failure, maintenance, and cold starts are unproven.
4. **PARTIAL:** Modular configuration exists; heterogeneous worker creation, retirement, and physical power management are not an accepted automated lifecycle.
5. **NOT MET:** Durable-service failover, total-loss recovery, independent alerting, and maintenance availability remain material gaps.

**Findings, ranked**

1. **Critical — Backup success is not demonstrated disaster recovery.**  
   **Evidence:** [Recovery tasks](openspec/changes/build-talos-proxmox-homelab/tasks.md:55) leave isolated etcd restore, application recovery, and clean-environment total-loss rehearsal unchecked. The [manual backup script](scripts/homelab-backup-manual.sh:26) packages fixed September 12 configuration files and a host baseline, not current etcd or application data. Its “restore” is archive byte comparison. September 22 [evidence](platform/main-control-plane/evidence/2026-09-21-preflight.md:71) records newer snapshots on laptop and recovery Mac, but no fresh-disk recovery.  
   **Failure:** Laptop disk loss or primary storage failure leaves snapshots/configuration whose completeness and restoration time have not been demonstrated; loss of the whole site is worse. No measured RPO/RTO supports a durability promise.  
   **Fix:** Establish scheduled, independently retained etcd and application-consistent backups, freshness alerts, recoverable keys/state/artifacts, and a clean-machine restoration exercise with measured RPO/RTO. Talos documents [snapshot-based recovery](https://docs.siderolabs.com/talos/v1.7/build-and-extend-talos/cluster-operations-and-maintenance/disaster-recovery); restarting the original disk does not exercise it.

2. **High — The laptop remains the sole control-plane failure domain.**  
   **Evidence:** The [accepted runbook](docs/runbooks/main-control-plane.md:11) retains one control plane; its [systemd unit](platform/main-control-plane/systemd/main-control-plane.service:19) explicitly uses `Restart=no`. [Preparation](platform/main-control-plane/prepare-host.sh:21) does handle lid closure and mask suspend.  
   **Failure:** Battery exhaustion, SSD failure, Wi-Fi loss, Ubuntu maintenance, or an unexpected QEMU exit removes API/scheduling/reconciliation. Existing worker containers may continue, but replacement scheduling cannot. Reboot recovery is proven; continuous availability is not.  
   **Fix:** Either declare and test this outage contract, including battery/power handling and guarded process recovery, or use three always-on control-plane members across independent failure domains with reliable networking. Sleeping workers cannot also be relied upon for always-available quorum.

3. **High — Two workers provide no durable-storage redundancy.**  
   **Evidence:** [StorageClass](kubernetes/platform/main/placement/storage-class.yaml:8) uses `rancher.io/local-path`, not a replicated CSI backend. [Placement code](kubernetes/platform/main/placement/plan.py:78) pins `apps-db` to primary storage. The [inventory](docs/homelab-network-inventory.md:53) explicitly gives worker 02 only an OS disk.  
   **Failure:** Primary host/array loss makes databases, Nexus, and other local-PV consumers unavailable despite a healthy secondary. Moving Pods cannot move their data; `Retain` protects against deletion, not disk loss.  
   **Fix:** Define durability and availability per service. Use tested backup-based recovery where downtime is acceptable; otherwise provide supported replicated application/storage placement across independent hosts. Explicitly design quorum and fencing before adding automatic database promotion. Two copies alone do not establish safe partition behavior.

4. **High — Main-cluster “autoscaling” is manual maintenance, with no automatic wake guarantee.**  
   **Evidence:** [Manual sleep/wake](docs/runbooks/manual-server-sleep.md:3) explicitly excludes automatic wake/shutdown triggers. The future IMM controller is [not deployed](docs/plans/talos-two-worker-operations.md:143). [Worker 02 remains cordoned](docs/homelab-network-inventory.md:34).  
   **Failure:** Demand arrives while execution hosts sleep, or primary fills while secondary remains cordoned: work cannot obtain capacity without an operator. Pilot autoscaler evidence does not prove main-cluster lifecycle behavior.  
   **Fix:** Implement an always-on demand/power reconciler with durable intent, bounded retries, readiness-gated capacity, PDB-respecting eviction, drain completion, and crash-resume tests. Distinguish “unreachable” from “powered off”; fence an old writer before replacement. [PDBs govern voluntary disruptions](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/), not sudden power loss. The seven-day partition document is explicitly [proposed](docs/plans/network-partition-resilience.md:5), not acceptance evidence.

5. **High — The monitoring system cannot reliably notify you of its own failure.**  
   **Evidence:** [Alertmanager configuration](kubernetes/platform/main/monitoring/config/alertmanager.yml:9) has a receiver without notification integration. The [sleep procedure](docs/runbooks/manual-server-sleep.md:78) stops monitoring on primary shutdown. `ControlPlaneUnavailable` checks [kubelet scraping](kubernetes/platform/main/monitoring/config/alerts.yml:14), not API readiness or etcd health.  
   **Failure:** Primary crashes and the monitoring/notification path disappears with it. API failure with a responsive kubelet may evade the named control-plane alert.  
   **Fix:** Add an independent external heartbeat and API/service probes, deliver alerts outside the cluster, and test notification with primary and control plane unavailable. Include backup freshness and host storage/power health.

6. **High — Zero-downtime upgrades are incompatible with the implemented placement.**  
   **Evidence:** [Primary maintenance](docs/runbooks/manual-server-sleep.md:73) deliberately stops front ends, hibernates CNPG, and stops platform controllers. The control plane is also a singleton.  
   **Failure:** Primary Proxmox or worker Talos reboot interrupts persistent services; control-plane maintenance interrupts management. Secondary capacity cannot compensate for primary-local data.  
   **Fix:** Publish maintenance windows and measured recovery limits now. Before promising uninterrupted upgrades, add independent replicas, accessible durable data, spare capacity, and rehearsed Talos/Kubernetes/Proxmox upgrade and rollback procedures. PDBs cannot manufacture replacement capacity.

7. **High — Add/remove is not an automated, idempotent worker lifecycle.**  
   **Evidence:** [Worker join](docs/plans/talos-two-worker-operations.md:82) requires manual vacancy checks, plan review, machine-config application, and acceptance. [Secondary IaC](live/proxmox/homelab-secondary/main.tf:77) prevents destruction and enforces one fixed aggregate allocation. The [primary root remains unapplied/unimported](docs/runbooks/main-control-plane.md:149).  
   **Failure:** Removing a VM-map entry does not perform safe drain/retirement; adding a GPU worker requires coordinated changes outside a single reconciled workflow. Interrupted operations require operator interpretation.  
   **Fix:** Separate protected stateful workers from disposable capacity. Implement identity allocation, provisioning, join/acceptance, drain, credential retirement, deletion, and interrupted-operation recovery as explicit resumable phases.

8. **Medium — Conflicting topology documents make recovery instructions hazardous.**  
   **Evidence:** [CONTEXT.md](CONTEXT.md:7) describes three Proxmox Talos VMs plus an Ubuntu GPU worker. The current [inventory](docs/homelab-network-inventory.md:14) records laptop CP plus two workers. [pilot/README.md](pilot/README.md:3) still describes a running pilot, while migration evidence records its retirement.  
   **Failure:** An operator follows obsolete reconstruction instructions or assumes nonexistent GPU capacity.  
   **Fix:** Establish one authoritative topology and clearly mark superseded plans and pilot procedures.

**Blockers versus nice-to-haves**

Blockers: demonstrated recovery with RPO/RTO, independent alert delivery, explicit availability/maintenance contracts, and validated worker lifecycle behavior. HA and replicated storage become blockers wherever uninterrupted service is promised.

Nice-to-haves: richer dashboards, faster pilot autoscaler tuning, additional platform tools.

**What is good**

Recorded physical sleep/wake and laptop recovery tests are substantive. Source-VM fencing, preserved identities, UID/spec guards, ordered database hibernation, independent management access, and refusal to bypass shutdown failures are strong operational safeguards. They establish disciplined maintenance, while leaving the availability and disaster-recovery gaps above explicit.