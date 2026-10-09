**Verdict**

The automatic-power controller is unusually careful: write-ahead journaling, UID/resourceVersion-guarded patches, fail-closed classification, no forced power-off, and real acceptance evidence. But the reliability posture around it is thin. Every failure mode collapses to a silent "blocked" state that only a human reading a laptop journal can clear, while the only alerting stack lives on the worker that sleeps after five minutes and has no notification receiver. The single control plane is a QEMU process with `Restart=no` on a laptop; etcd RPO is 24 h; application volumes other than `apps-db` have no backup; secondary-host IaC state lives on a personal Mac; and worker identity is hard-coded across four modules, so adding the GPU worker the operator wants is a code change, not configuration. Production-like for correctness, not yet for recoverability or observability.

**Findings**

**F1 — Severity: High.** Claim: A demand arrival between quiesce and Talos shutdown leaves the host permanently "blocked" with applications already scaled to zero and CNPG hibernated, contradicting the README's "new demand cancels before Talos shutdown."
Evidence: `controllers/homelab-capacity/src/homelab_capacity/coordinator.py:294-305` (`stop-worker` re-observes and `raise RuntimeError("Demand/activity changed before shutdown commit")`); `coordinator.py:365-370` catches and calls `complete(..., error=...)`; `lifecycle.py:169-175` sets `phase = "blocked"`; `lifecycle.py:81-82` returns `None` forever while blocked; `platform/automatic-power/README.md:24`.
Status: IMPLEMENTED-BUT-FLAWED.
Failure scenario: Primary idles 300 s, quiesce completes (Nexus, CNPG, monitoring at 0 replicas, node cordoned). A user hits the Ollama gateway 5 s before the commit tick. `stop-worker` raises, host is blocked; the gateway 503s indefinitely, CI Workloads stay Pending, nobody is notified. Operator must SSH to the laptop and run `powerctl resume`.
Fix: In `effect("stop-worker")`, return a distinct `Cancelled` outcome that `complete()` maps to `phase="restoring"` (same as the `cancel` action) instead of an error; add a lifecycle test for it.
Confidence: High.

**F2 — Severity: High.** Claim: There is no path by which a down control plane, a blocked coordinator, or a stuck host reaches a human; alerting is UI-only and runs on the host that sleeps.
Evidence: `kubernetes/platform/main/monitoring/config/alertmanager.yml:9-11` (`receivers: - name: local` with no config; comment "External notification routing is not configured"); `alerts.yml:14-18` (`ControlPlaneUnavailable` critical); Prometheus/Alertmanager are in the quiesce list `platform.py:21-25` and `policy.py:24-26`; `docs/runbooks/main-control-plane.md:182`; coordinator errors go only to journal/stdout `coordinator.py:392-395`, `471-481`. Only external signal is the daily etcd-backup heartbeat alarm at ~30 h `live/aws/staging/workloads/homelab-recovery/daily-backup.tf:50-57`.
Status: MISSING.
Failure scenario: Laptop QEMU dies at 07:00; workers are asleep. Nothing scrapes, nothing pages. First indication is the 30-hour-stale backup alarm the following afternoon.
Fix: Add an external dead-man (e.g., CloudWatch alarm on a 5-min heartbeat pushed by `verify-independence.py` from the laptop via cron/systemd timer, reusing the `Homelab/Recovery` namespace and SNS topic); have the coordinator push a metric on `blocked` transitions; configure at least an email receiver in Alertmanager.
Confidence: High.

**F3 — Severity: Medium.** Claim: The single control plane is a QEMU process that is never restarted on crash.
Evidence: `platform/main-control-plane/systemd/main-control-plane.service:19` (`Restart=no`), `:9-13`; `launch.sh:11` single `exec flock -n vm.lock qemu-system-x86_64`.
Status: IMPLEMENTED-BUT-FLAWED (deliberate for failed *shutdowns*, but also covers crashes).
Failure scenario: QEMU segfault or OOM kill on the laptop leaves the API, etcd, CoreDNS, Pi-hole and all gateways down until someone runs `ops.sh restart`; the coordinator cannot even observe (all `kubectl` calls fail).
Fix: `Restart=on-failure` with `RestartSec` and a `StartLimitBurst`, keeping `SendSIGKILL=no` and the ACPI stop path; combine with F2 so a restart loop is visible.
Confidence: High.

**F4 — Severity: Medium.** Claim: All persistent application data lives on one local-path XFS partition on the primary worker's single virtual disk, and only `apps-db` is backed up off-site.
Evidence: `config/environments/talos/homelab/local-path-values.yaml:10-13` (single node, single path); `docs/plans/homelab-worker-storage.md:12-13` ("No ... application-data backup is provided"); `scripts/homelab-backup.py:145` (`'scope': ... no application volume data`); `docs/apps-postgres.md` backup section covers only `apps-db`; RAID drives at ~6 years with grown defects `docs/plans/serveraid-health-monitoring.md:4-25`.
Status: MISSING.
Failure scenario: Array or filesystem loss on primary destroys Nexus (CI cache and Roles-Anywhere refresher state), Nexus Postgres, Loki/Prometheus history, Ollama models and the original Pi-hole claim with no restore path.
Fix: Extend the daily backup Job pattern (dump-verify-promote-heartbeat) to Nexus Postgres and a Restic/rclone snapshot of the remaining claims to the recovery bucket; document explicit RPO/RTO per volume.
Confidence: High.

**F5 — Severity: Medium.** Claim: The secondary Proxmox root and worker-02 are outside CI and shared state.
Evidence: `live/proxmox/homelab-secondary/versions.tf:1-9` has no backend; README `:22-25` ("Local state ... backed up in the private join directory ... Off-site state recovery remains separate"); `deploy-units.json:229-240` (`"ci": false`); `live/talos/homelab/main.tf:50-60` applies only worker `10.0.0.222`; `docs/runbooks/main-cluster-iac.md:14`.
Status: IMPLEMENTED-BUT-FLAWED.
Failure scenario: Admin Mac is lost; nobody can plan against VM 103 without risking recreation; worker-02 Talos config drifts undetected because no root reapplies it.
Fix: Migrate to the existing S3 backend with key `proxmox/homelab-secondary/terraform.tfstate` (backed-up, explicit migration), set `ci: true` plan-only, and add a second `talos_machine_configuration_apply` guarded by a variable.
Confidence: High.

**F6 — Severity: Medium.** Claim: Worker identity is hard-coded in code, so a re-joined node or a new heterogeneous worker requires source changes in four modules, and a recreated node object silently disables wake.
Evidence: `controllers/homelab-capacity/src/homelab_capacity/config.py:6-23` (node UIDs, system UUIDs, IPs); `policy.py:9`; `kueue.py:7`; `lifecycle.py:9`; `lifecycle.py:83-86` (`identity_ok` false → `return None` with "Power or registered identity is unknown").
Status: IMPLEMENTED-BUT-FLAWED.
Failure scenario: A Talos reset/rejoin of worker-01 gives a new node UID. The coordinator never wakes it again; CI admission is gated forever; no alert (F2). Adding a GPU host means editing Python, tests, Kueue flavors, and redeploying the management root.
Fix: Move inventory to a versioned, private JSON validated at load; register hosts by (node name, system UUID) and record node UID at enrolment with an explicit `powerctl enroll` command; keep the fail-closed check.
Confidence: High.

**F7 — Severity: Medium.** Claim: One 20-minute deadline spans the entire cold-wake chain (BMC power-on, POST, Proxmox boot, VM start, Talos/Cilium readiness, ordered platform restore with 20 s waits), after which the host blocks.
Evidence: `lifecycle.py:64` (`recovery_seconds=1200`), `:105-106` (set on first effect), `:143-146` (kept while waiting for Proxmox), `:152` (cleared only at `ready`), `:87-90` (blocked on expiry); restore waits `platform.py:153-164, 185-192`. Evidence file records no wake duration (`platform/automatic-power/evidence-20260922.md:98-102`).
Status: IMPLEMENTED-BUT-FLAWED.
Failure scenario: A slow RAID controller POST plus a CNPG recovery after unclean hibernation pushes past 1200 s; host blocks with apps half-restored.
Fix: Separate deadlines per phase (power-on, node-ready, restore) and make them configurable and observable; record measured wake time in evidence.
Confidence: Medium.

**F8 — Severity: Medium.** Claim: The coordinator is a user-scope systemd unit and the host preparation never enables lingering, so it may not run after a laptop reboot until interactive login.
Evidence: `platform/automatic-power/homelab-coordinator.service:8,19-20` (`%h`, `WantedBy=default.target`); `docs/runbooks/automatic-server-power.md:74` (`journalctl --user`); `prepare-host.sh:22-27` and `autopower-prepare-wizard.sh` contain no `loginctl enable-linger`.
Status: IMPLEMENTED-BUT-FLAWED.
Failure scenario: Power blip reboots the laptop; the VM service (system scope) returns but no coordinator runs, so no wake and no Kueue readiness until someone logs in.
Fix: Add `loginctl enable-linger tushar` to the wizard (or convert to a system unit with `User=`), and document it in the runbook.
Confidence: Medium.

**F9 — Severity: Low.** Claim: Re-rendering coordinator config silently resets both hosts to `observe`, which disables wake, not just shutdown.
Evidence: `platform/automatic-power/render-config.py:19,33-35` (copies `coordinator.example.json`, `modes` = observe); `lifecycle.py:96-100`; runbook warning `automatic-server-power.md:35-36`.
Status: IMPLEMENTED-BUT-FLAWED.
Failure scenario: Operator changes `idleTimeoutSeconds`, re-renders, copies the file; next reload leaves hosts off with CI queued.
Fix: Have `render-config.py` accept `--preserve-modes-from EXISTING` or refuse to overwrite a file whose modes differ.
Confidence: High.

**F10 — Severity: Low.** Claim: There is no Talos or Kubernetes upgrade procedure for the laptop control plane or workers.
Evidence: No `talosctl upgrade`/`upgrade-k8s` references in `scripts/`, `.github/`, `docs/runbooks/`; CP VM lifecycle is `launch.sh` outside any root; `live/talos/homelab/main.tf:26-34` only applies config in `no_reboot` mode.
Status: MISSING.
Failure scenario: A Talos CVE requires an image upgrade of a single-etcd VM with no rehearsed snapshot-then-upgrade path.
Fix: Add a runbook and CI job: fresh `homelab-backup.py capture`, `talosctl upgrade` CP first with `--preserve`, then workers under a durable power hold.
Confidence: Medium.

**Strengths**

- Effects are journaled write-ahead with fsync and atomic rename (`journal.py:38-55`), and every Kubernetes mutation is UID+resourceVersion guarded (`kube.py:115-133`).
- Shutdown is genuinely fail-closed: unknown pods, unfinished backups, missing telemetry, stale gateway leases and unexpired CI holds all block retirement (`policy.py`, `coordinator.py:145-200`).
- The daily etcd backup verifies the embedded checksum, uploads with SHA-256, reads back the exact version, and only then publishes a heartbeat with an independent missing-data alarm (`scripts/homelab-backup.py:165-185`, `daily-backup.tf:50-76`).
- No forced BMC power-off anywhere; IMM adapter allowlists only `power state`/`power on` (`imm2.py:62-65`).
- Acceptance is evidence-gated (`require_acceptance`, `coordinator.py:313-319`) and the rollout record is specific and dated.