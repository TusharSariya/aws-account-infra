# Retained-worker automatic power management

The live installation uses **automatic** mode with a **300-second idle threshold**.
Both retained hosts have passed a real timed graceful shutdown; the final cold-wake
and persistence results are recorded in `evidence-20260922.md`. New installations
start in read-only `observe` mode and require private commissioning receipts before
shutdown is permitted. Kueue holds work until its host and dependencies are ready.

## Ownership

Ubuntu runs the single power coordinator. It retains worker 01 (VM 102) and worker
02 (VM 103), and uses direct management addresses, a restricted Proxmox SSH key,
and the existing IMM status/wake adapter. No VM creation, deletion, forced power
off, cluster bootstrap, or storage replacement is part of the controller.

`powerctl --config PRIVATE.json status|wake|shutdown|pause|resume HOST` operates
through a private local journal. `hold HOST --token ID --reason TEXT` prevents
retirement until `release HOST --token ID`; holds intentionally survive crashes.
A normal shutdown leaves automation armed. Pause persists until explicit resume.

The controller journals an effect before executing it. Interrupted or ambiguous
operations block for explicit inspection. Idle time is monotonic, requires complete
observations, and resets after process restart, a timeout change, or an observation
gap. The configured idle period is currently **300 seconds (5 minutes)**. New demand cancels before Talos shutdown;
after that point shutdown completes before another wake. Platform snapshots retain
UIDs, storage bindings, original replicas, schedule settings, and node state.

Kueue's custom admission check waits for the assigned worker and its dependencies.
Secondary CI still depends on primary Nexus. Housekeeping schedules never wake a
server or reset application idle time; an unfinished housekeeping job must finish
before shutdown. Unregistered
workloads prevent shutdown. Monitoring and Argo CD remain primary-host services.

## Idle timeout

The versioned source is `config/environments/kubernetes/homelab/lifecycle-values.yaml`,
`config.idleTimeoutSeconds`. The management Helm root uses it for AI idling, and
`render-config.py` copies it to the laptop coordinator's `idle_seconds`. The laptop
accepts integer values from 60 to 86400 seconds. Update both deployments together.
The daemon reloads `idle_seconds` and rollout modes between reconciliation cycles;
a change starts a fresh idle window and leaves an in-progress recovery intact.
Credential, inventory, and budget changes require a service restart.

Five minutes is the idle threshold, not a forced power-off deadline. Active work,
backups, maintenance holds, missing telemetry, or unknown workloads block shutdown.
Graceful application, worker VM, and physical host shutdown follows the idle period.

## Implementation and acceptance checklist

- [x] Private crash-durable journal and pure lifecycle state machine.
- [x] Kueue dependency selection and guarded admission-status patches.
- [x] Bounded retained-host management endpoint and platform restoration code.
- [x] Tests for idle gaps, unknown power, maintenance pause, demand races, and job policies.
- [x] Laptop launcher installed: 2 vCPU / 5 GiB, dedicated 4 GiB DNS disk.
- [x] Private pre-change etcd snapshot and protected-storage inventory captured.
- [x] Control-plane restart, API recovery, dedicated 2 GiB Talos volume mounted.
- [x] Initial controller integration tests and read-only deployment.
- [x] AdmissionCheck Active status, gateway demand/activity protocol, health budgets.
- [x] Pi-hole consistent copy, retained claim cutover and DNS acceptance.
- [x] Always-on controller/proxy placement deployed and measured.
- [x] Explicit OpenTofu state migration and all three provider plans verified.
- [x] Application gateway wake/authentication, bounded streaming unit tests and live forward helper.
- [x] CI maintenance holds and potential-versus-ready capacity checks.
- [x] Wake-only acceptance from both servers off and Kueue overflow.
- [x] Secondary, then primary automatic shutdown acceptance (real configured 5-minute window).
- [x] Both-hosts-off DNS/API/Pi-hole checks and coordinator restart.
- [x] Cold-wake CI completion, post-cycle storage/monitoring/Argo recovery and restored schedules.

The physical laptop reboot/Wi-Fi cycle was proved during the earlier migration,
not repeated during this rollout. See the explicit scope note in the evidence.

The private `acceptance.json` requires `always_on`, `dns`, `capacity`, `storage`,
`wake`, and `independence` true, and an explicit `shutdown_hosts` list. Receipts are
written only after live evidence, never as a workaround for failed checks.

## Laptop preparation

`platform/main-control-plane/autopower-prepare-wizard.sh` installs the reviewed
launcher and adds the dedicated DNS disk. It needs interactive Ubuntu sudo and
does not restart a service. The previous launcher is retained root-only at
`/var/lib/main-control-plane/launch-before-autopower.sh`. DNS storage is selected by
the serial-derived stable disk symlink, never `/dev/sdb` enumeration or system disk.

Private recovery evidence from the initial preparation is on the laptop under
`~/.local/share/main-control-plane/autopower-recovery-20260922T174655Z/`.

## Validation

```sh
uv run --with pytest --project controllers/homelab-capacity python -m pytest controllers/homelab-capacity/tests
helm lint charts/homelab-queue
helm template test charts/homelab-queue --set power.enabled=true
```

Rollback disables the coordinator, retains all journals and disks, and uses the
manual recovery runbook. Pi-hole rollback must copy its latest consistent data.
