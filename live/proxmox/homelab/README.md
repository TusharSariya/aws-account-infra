# Primary Proxmox worker

The main control plane runs on Ubuntu `10.0.0.181`, retaining node `.221` and
API VIP `.231`. This root owns **only worker 01**, VM 102 on PVE `.224`.
VM 100 is a protected, stopped, stale recovery copy with autostart disabled.
Never start it without the latest-state reverse migration procedure.

| Guest | vCPU | RAM | Disks | Address |
| --- | --- | --- | --- | --- |
| talos-worker-01 / 102 | 38 | 112 GiB | 320 GiB OS + 1200 GiB data | 10.0.0.222 |

Worker 02 is in `../homelab-secondary`. Both worker roots preserve runtime power
with `ignore_changes = [started]`: manual sleep/wake owns that state. New VMs
start stopped; `on_boot = true` allows a worker to start when its physical host is
explicitly woken. No idle timer or automatic host wake/shutdown is installed.

The existing S3 backend key is `proxmox/homelab/terraform.tfstate`. Contrary to the
old migration checkout's notes, this state already owned both primary VMs. On
2026-09-22 it was privately backed up and exactly
`proxmox_virtual_environment_vm.guest["talos-cp-01"]` was removed with state locking.
Worker 01's state was unchanged; **do not import it again or initialize empty state**.
The state-based plan (`-refresh=false`) has no resource changes. A live refreshed
plan still requires the physical host to be awake.

The `vms` validation admits only worker 01 / VM 102 / `.222`, so a renamed entry
cannot recreate the retired control plane. `prevent_destroy` protects the worker.
The retired optional CI VM remains disabled and cannot satisfy its capacity gate.
Never apply a pre-migration branch or restore pre-retirement state without review.

Local checks:

```sh
tofu -chdir=live/proxmox/homelab init -backend=false -lockfile=readonly
tofu -chdir=live/proxmox/homelab validate
tofu -chdir=live/proxmox/homelab test \
  -var-file=../../../config/environments/proxmox/homelab/vms.tfvars
```

Mock tests do not contact PVE. Preserve the existing encrypted S3 backend and
locking for real state operations. Live provider TLS verification remains enabled.
CI identity bootstrap now grants only VM 102. Existing VM 100 ACLs must be removed
from both user and token identities on the next approved host wake; the updated
preflight refuses their old scope rather than silently retaining write access.

See [IaC reconciliation](../../../docs/runbooks/main-cluster-iac.md),
[control-plane recovery](../../../docs/runbooks/main-control-plane.md), and
[manual sleep/wake](../../../docs/runbooks/manual-server-sleep.md).
