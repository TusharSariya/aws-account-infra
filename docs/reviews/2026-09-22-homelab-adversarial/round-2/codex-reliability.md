1. **Verdict**

At `000bb81`, routine sleep/wake operations have substantial safety controls, but recovery readiness falls short of the production-like goal. The largest gaps are loss of laptop-local recovery state, ineffective outage notification, and application backups that cannot accommodate the configured data capacity. Etcd backup integrity checks are useful, but a replacement-control-plane restore and measured recovery time remain unproved. This assessment used repository reads only; no commands contacted infrastructure, and no prior reviews were read.

2. **Findings**

**F1**
- **Severity:** High
- **Claim:** Recovery from a sleeping cluster depends on laptop-local journals that the recurring etcd backup does not capture.
- **Evidence:** `docs/runbooks/automatic-server-power.md:72` locates recovery journals on the laptop. `controllers/homelab-capacity/src/homelab_capacity/platform.py:141` reads original replicas from the saved record; `platform.py:243` returns without restoring anything when that record is absent. `scripts/homelab-backup.py:114`–`147` captures etcd, Talos identity and reconstruction configuration, without the power journals.
- **Status:** MISSING
- **Failure scenario:** The laptop disk fails while workers are asleep. Restoring an etcd snapshot taken during sleep recovers cordoned nodes, scaled-down services and hibernated PostgreSQL, but loses the journal needed to reverse those changes. Normal coordinator wake cannot restore the saved application state.
- **Fix:** Preserve encrypted, versioned power journals independently of the laptop, coordinated with recovery snapshots. Add a tested missing-journal recovery procedure that validates storage and reconstructs intended replicas, schedules and cordons.
- **Confidence:** High

**F2**
- **Severity:** High
- **Claim:** Cluster alerting cannot notify the operator externally and disappears entirely during primary-host sleep.
- **Evidence:** `kubernetes/platform/main/monitoring/config/alertmanager.yml:9`–`11` defines only an empty `local` receiver and explicitly says external routing is unconfigured. `controllers/homelab-capacity/src/homelab_capacity/platform.py:21`–`25` includes Prometheus and Alertmanager in the shutdown order; `platform.py:231`–`239` scales those services down. The separate backup-staleness alarm is documented at `docs/plans/homelab-recovery.md:203`–`208`.
- **Status:** IMPLEMENTED-BUT-FLAWED
- **Failure scenario:** Both workers sleep, then the laptop or its network fails. No cluster monitoring remains to detect the outage; even while monitoring runs, alerts have no external destination. A later missed-backup alarm does not provide timely service-outage detection.
- **Fix:** Configure and test an external notification receiver plus an independently hosted heartbeat/synthetic check covering API reachability and coordinator progress. Distinguish intentional worker sleep from failed wake or laptop loss.
- **Confidence:** High

**F3**
- **Severity:** High
- **Claim:** The AI backup implementation rejects all three volumes together once their combined contents exceed 2 GiB.
- **Evidence:** `apps/platform/recovery/archive.py:12`–`14` defines the three-volume scope and 2-GiB maximum; `archive.py:76`–`78` raises an error above that limit. Configured capacities are 300 GiB, 20 GiB and 10 GiB at `config/environments/kubernetes/homelab/ai-values.yaml:8`–`20`.
- **Status:** IMPLEMENTED-BUT-FLAWED
- **Failure scenario:** Downloading a model larger than 2 GiB makes the complete backup fail, including otherwise-small workspace and vector data. A subsequent primary-storage failure loses user data accumulated since the last successful capture.
- **Fix:** Support backups and isolated restores at realistic dataset sizes, provisioning sufficient scratch capacity. Alternatively, independently back up irreplaceable workspace/vector data and maintain a verified model-reconstruction manifest, with separate coverage for custom models.
- **Confidence:** High

**F4**
- **Severity:** High
- **Claim:** AI data recovery has no implemented recurring backup schedule or verified durable off-machine retention.
- **Evidence:** `.github/workflows/homelab-lifecycle-maintenance.yml:2`–`13` exposes workflow-call and manual triggers, without a schedule; line `55` limits artifacts to 90 days. `docs/homelab-lifecycle.md:55` explicitly states that no durable copy is claimed until verified, and line `63` states local maintenance records have no automatic off-machine copy.
- **Status:** MISSING
- **Failure scenario:** AI data changes for weeks without an operator-selected maintenance rehearsal. The primary disk fails, leaving only an old backup, or the last CI artifact has expired.
- **Fix:** Implement recurring consistent application backups to independently retained encrypted storage, with a defined RPO, missed-backup alert and periodic restoration checks. Keep backup execution separate from the disruptive lifecycle acceptance suite.
- **Confidence:** High

**F5**
- **Severity:** High
- **Claim:** Recovery of the sole control plane onto replacement infrastructure remains an uncompleted acceptance task.
- **Evidence:** `docs/plans/homelab-recovery.md:122`–`128` records deferred clean-machine recovery and undefined recovery objectives; lines `218`–`220` stop at archive verification and leave restore drills separate. `docs/plans/talos-kubernetes-rebuild.md:334`–`340` lists disposable etcd restoration and full reconstruction as acceptance requirements.
- **Status:** PLANNED-ONLY
- **Failure scenario:** The laptop becomes unrecoverable. Valid encrypted snapshots exist, but the operator must discover replacement networking, identity recovery and actual Talos/etcd restoration steps during the outage. Routine reboot and migration success do not establish this recovery time.
- **Fix:** Restore a recent backup into an isolated replacement control plane using independently recovered credentials. Verify Kubernetes objects and application dependencies, document the exact procedure, and record achieved RPO/RTO.
- **Confidence:** High

**F6**
- **Severity:** Medium
- **Claim:** The secondary worker’s authoritative OpenTofu state remains local, with off-site recovery explicitly unfinished.
- **Evidence:** `live/proxmox/homelab-secondary/README.md:22`–`25` says state is backed up in the private join directory and off-site recovery remains acceptance work. `docs/runbooks/main-cluster-iac.md:15` identifies preserved private local state as the secondary hardware’s canonical owner.
- **Status:** IMPLEMENTED-BUT-FLAWED
- **Failure scenario:** Loss of the administration machine removes both working state and its private local backup. The existing VM survives, but safe reconciliation requires manual state reconstruction/import before further infrastructure changes.
- **Fix:** Migrate the existing state into a distinct encrypted, versioned, locked remote backend. Preserve a pre-migration copy and verify a refreshed no-change plan and independent state recovery.
- **Confidence:** High

3. **Strengths**

- Power transitions use durable journals, atomic replacement and file/directory `fsync`.
- Unknown workloads, incomplete observations and durable maintenance holds prevent automatic shutdown.
- Restoration checks resource UIDs, storage bindings and cordon ownership before resuming services.
- Etcd backups verify snapshot integrity and exact uploaded versions; backup staleness has an independent alarm.
- CI maintenance acquires worker holds, and infrastructure ownership explicitly separates runtime power state from VM configuration.