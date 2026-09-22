# Manual application-server sleep and wake

Run from the Ubuntu laptop, using the private main-cluster kubeconfig and Talos
credentials. This procedure has no web portal, automatic wake or shutdown trigger,
idle timer, or Kubernetes dependency for host power control. Do not use it until
the relocated main control plane passes the independence gate below.

| Host | PVE address | IMM address | Worker VM | Talos address |
| --- | --- | --- | --- | --- |
| Primary | 10.0.0.224 | 10.0.0.98 | 102 | 10.0.0.222 |
| Secondary | 10.0.0.223 | 10.0.0.67 | 103 | 10.0.0.225 |

Use separately tested direct-IP SSH/BMC credentials on the laptop. Check the IMM
CLI `help` and `power` status for the installed firmware; do not assume another
vendor's command or use a forced power-off. Keep credentials outside Git and out
of command-line arguments. A browser may use the direct IMM address if its SSH
firmware does not support the required power action. Test independent management
access before stopping anything. Copy the runbook and private tools locally;
Pi-hole, Argo, Nexus and application Tailscale proxies may all be offline.

## Before the first primary shutdown

Prove VM 100 stopped/onboot=0/protected at PVE; prove the main QEMU process and
systemd service run on the laptop; verify API .231, etcd .221 and original cluster
UIDs; ensure CoreDNS and Cilium operator run on the CP and their DNS upstream is
independent of Pi-hole. Confirm CP taints and node networking agents remain.
Confirm the laptop holds independent management credentials and no recovery tool
must be pulled from Nexus. Record evidence in private `independence.json` with
`passed: true` only after checking those facts. `maintenance.py check --host primary`
refuses without that receipt and a running local main control-plane service.

## Ordered sleep procedure

1. Create a new private operation journal before changing desired state:

   ```sh
   python3 ~/main-control-plane/maintenance.py snapshot --host secondary \
     --kubeconfig ~/.local/share/main-control-plane/private/kubeconfig \
     --journal ~/.local/share/main-control-plane/maintenance/UNIQUE-UTC
   ```

   Use `primary` for primary-host maintenance. The journal records controller
   replica counts, schedules, runner desired ranges, nodes/cordons, CNPG state,
   Argo application policy, storage and intent. Never overwrite a previous journal.
2. Pause external submissions for this window. Suspend the recorded Kubernetes
   CronJobs, CronWorkflows and CNPG ScheduledBackups, preserving each prior suspend
   value. Set ARC minRunners/maxRunners to zero to stop accepting new work; let
   assigned runners finish. Suspend relevant CI schedules through their existing
   ownership, recording exactly what changed. Do not scale a busy runner away or
   cancel jobs to pass this gate. Stop user workflow submissions.
3. Disable automatic Argo sync where present, preserving prior policy, and pause
   other reconciliation that could recreate the workloads. The new Argo install
   has no Applications, but recheck each time. Leave CNPG running until database
   shutdown finishes; leave Kueue/ARC running until active work drains. Do not
   modify dormant AI desired state or storage. For both-host sleep, pause all
   application submissions before touching either host.
4. Wait until all active Jobs, Workflows, runner assignments and database backups
   complete. Inspect failed resources and queues; unscheduled/suspended work is
   not proof that submissions are paused. Run `maintenance.py check` using the
   same host, journal and kubeconfig. It fails closed for active jobs/backups,
   extant ephemeral runners, enabled schedules, runner capacity or auto-sync.
   This is a conservative cluster-wide check even for secondary maintenance.
5. Create an Alertmanager silence for `WorkerUnavailable` with an exact `node`
   matcher, an operator/comment containing the journal ID and a bounded end time
   longer than planned maintenance. Record the silence ID privately. For both-host
   sleep, silence both worker names while Alertmanager is still available. Keep
   `intent.json` as the authoritative maintenance record on the laptop: monitoring
   is itself unavailable while primary sleeps. Reconcile/extend silences before
   their expiry; do not permanently suppress unexpected failure alerts.
6. Cordon the target worker. For secondary, use Pod eviction respecting PDBs and
   wait for eligible work to finish; never use force or delete emptyDir data without
   auditing it. Refuse shutdown if any persistent/local data consumer is there.
   For primary, stop application front ends/access proxies first, then gracefully
   scale persistent applications down using the saved desired state. Hibernate
   CNPG with annotation `cnpg.io/hibernation=on`, wait for condition `cnpg.io/hibernation=True` with reason `Hibernated`
   and all its Pods to terminate, then stop CNPG controller. Do not scale CNPG's
   generated Pods or delete claims. ScheduledBackups must already be suspended.
7. Stop remaining platform controllers after their dependents stop: workflow,
   ARC/listeners, Kueue, capacity collectors and access proxies. Account for
   controller-owned proxy Pods through their owner/operator. Stop Argo, then Alloy,
   Grafana, Prometheus, Loki and Alertmanager last. Preserve all replicas and prior
   annotations in the journal. Do not blindly scale every namespace or delete a
   namespace. Confirm target Pods are terminated except required node DaemonSets;
   inspect any survivors, mounts and finalizers instead of bypassing them.
8. Gracefully shut down the target Talos node using its direct IP and private
   talosconfig. Verify the corresponding `qm status VMID` reports stopped on its
   PVE host. Verify there are no other running VMs/containers or unrelated host
   users before `systemctl poweroff` over direct PVE SSH. If anything remains,
   stop and inspect. Never use IMM forced power-off for routine maintenance.
9. Verify IMM reports host off. Update the journal phase to `sleeping` with time.
   Check laptop API/etcd/DNS continuously. For primary sleep, monitoring and Argo
   are intentionally unavailable. Do not interpret their absence as data loss.

## Wake and restore

1. From the laptop, power on through the target's direct IMM endpoint. Wait for
   its direct PVE address and inspect hardware/storage health. In particular,
   secondary CacheVault remains a known maintenance issue; keep safe write-through
   settings. Verify primary VM 100 is still stopped and onboot=0.
2. Start only worker VM 102 or 103 if it did not autostart. Verify Talos at the
   direct node IP, correct node UID, node/network readiness and mounted storage.
   On primary, verify the existing data disk/mount and all protected PV/PVC UIDs,
   bindings and affinity match the journal before allowing writes. Do not create
   replacement claims or allow an OS-directory fallback.
3. Once storage verification passes, restore the primary worker’s original
   schedulability so controller Pods can start (leave an originally cordoned node
   cordoned). Restore storage provisioner, Kueue admission/controller and CNPG controller first.
   Wait for their webhook endpoints before changing application CRs or Jobs. Clear only the CNPG
   hibernation annotation introduced by this operation, preserving any prior
   value, and wait for database readiness. Restore Nexus PostgreSQL, Nexus,
   Pi-hole and other saved persistent apps in dependency order.
4. Restore monitoring and check its retained historical metric/log marker and
   unchanged claims. Import/reconcile the laptop maintenance intent with retained
   Alertmanager silences before enabling worker-down alerts. Restore Argo and
   confirm it makes no application changes. Restore other platform controllers
   and access proxies, then wait for healthy rollouts. On secondary-only wake,
   primary services should have stayed running.
5. Restore the target's original schedulability (do not uncordon a node that was
   already cordoned before maintenance). Restore saved runner ranges, workflows,
   schedules and relevant reconciliation **last**. Restore only this operation's
   changed fields, checking resource UIDs; do not replay whole stale object specs
   with old resourceVersions over concurrent edits. Keep dormant AI state unchanged.
6. Expire only this operation's silences after each node is healthy; verify alerts
   resolve. Mark journal `complete` with evidence but retain it outside Git.
   A partial wake keeps its intent and submissions paused.

Test secondary, primary, then both hosts off. Finally test laptop reboot and Wi-Fi
reconnection while both are off. This last check requires enabled main VM startup
and proves network/firmware/KVM recovery without the application servers. A normal
worker restart alone is not a successful both-host or laptop-reboot test.

If a wake fails, use direct IMM/PVE/Talos addresses and the saved journal. Do not
remove finalizers, change storage classes, or restore stale control-plane disks.
An expired silence is a visible maintenance overrun; extend it explicitly and
record why. Resume submissions only after recovery has passed all relevant checks.

References: [CNPG hibernation](https://cloudnative-pg.io/docs/1.30/declarative_hibernation/),
[ARC runner scale-set configuration](https://docs.github.com/en/actions/how-tos/manage-runners/use-actions-runner-controller/deploy-runner-scale-sets),
[Tailscale ProxyClass](https://tailscale.com/docs/kubernetes-operator/concepts/proxyclass).

The optional `verify-independence.py` helper creates one 8-MiB-request restricted
DNS probe on the laptop control-plane node. Run `prepare` before maintenance,
`check --output PRIVATE.json` at each off/recovery boundary, and `cleanup` after
all tests. It checks API readiness, etcd status and internal/external cluster DNS
using the laptop's local credentials. It does not power any host or change apps.

`platform-state.py stop --journal PRIVATE_DIRECTORY` performs the explicitly
allowed primary-platform scale-down and CNPG hibernation steps after repeating
submission checks. It leaves hosts and workers running. It checks each object's
UID and replica count, stops the Tailscale operator before its proxies, and stops
ARC before removing its idle listener Pods. `restore` uses the same snapshot in
dependency order after the operator verifies the data disk and schedulability.
Unknown or standalone workloads still require inspection and a separate saved
restore manifest. Neither command restores submissions or powers any host.

Capture the data-volume identity before primary maintenance (required by the
restore helper):

```sh
~/.local/share/main-control-plane/private/talosctl \
  --talosconfig ~/.local/share/main-control-plane/private/talosconfig \
  -e 10.0.0.222 -n 10.0.0.222 get volumestatus u-local-path-provisioner -o json \
  > PRIVATE_DIRECTORY/volume-before.json
```

After the workload and guest checks above, the tested direct management commands
are `ssh -i ~/.ssh/main-proxmox root@PVE_IP 'qm status VMID'` and
`ssh -i ~/.ssh/main-proxmox root@PVE_IP 'systemctl poweroff'`. Wake with
`ssh -o IdentityAgent=none -i ~/.ssh/main-imm USERID@IMM_IP 'power on'`;
`power state` reports actual off/on state. Do not infer off from an unreachable
PVE SSH port. The IBM hosts take several minutes through firmware before PVE SSH
returns. Start the worker with `qm start VMID` only if it did not autostart, and
confirm preserved source VM 100 remains stopped after every primary-host wake.

After every platform recovery check has passed, use
`resume-submissions.py --journal ORIGINAL_SUBMISSION_JOURNAL` to restore only the
prior suspend and runner min/max fields. Keep the original journal across multiple
maintenance tests; later snapshots may already contain paused values. The helper
refuses unrelated replica or submission changes instead of overwriting them.
The primary `maintenance.py snapshot` now captures `volume-before.json` itself;
the manual capture command above is useful for checking an older journal.
