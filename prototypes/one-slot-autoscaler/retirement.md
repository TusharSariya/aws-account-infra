# Explicit runtime retirement prototype

Implements the next bounded gate in [issue 108](https://github.com/TusharSariyaOrg/aws-account-infra/issues/108). `retire.py` runs on the Ubuntu laptop and owns only VM 9105 in the isolated cluster. This is an explicit runtime operation; CA automatic deletion RPCs and physical host shutdown remain disabled.

## Safety contract

The operator supplies the old Kubernetes node name and UID. Before mutation, the runtime verifies the isolated cluster endpoint/name, expected provider ID, non-control-plane role, VM presence, node IP and matching hardware UUID. Reused IPs or provider IDs alone are insufficient identity evidence.

A shared flock serializes provider scale-up acceptance, create/join and retirement. Observation RPCs stay responsive. Concurrent scale-up is refused for retry, never silently dropped. Retirement drains without force, waits for zero VolumeAttachments on the node, asks Talos for graceful shutdown and waits for PVE stopped state. Timeout or failed drain stops the operation; there is no hard-off fallback.

The forced-command host helper rechecks VM name, owner description, exact SMBIOS UUID, stopped state and disk references under its own lock. Only `scsi0=local-lvm:vm-9105-disk-0` plus the known Talos ISO is accepted. Additional attached, unused, EFI, TPM or foreign disks block destruction. It never destroys unreferenced disks, the retained volume owner, other guests or the template. On success, runtime removes the old Kubernetes node and atomically records desired size zero.

Failures leave visible systemd/journal evidence and preserve the target until retirement completes. Interrupted transitions require inspection; this prototype is not a crash-recovery state machine. External administrators or controllers must not mutate this guest concurrently. No automatic idle timer, app-movement decision, global demand cancellation or two-host consolidation is introduced here.

## Replacement access correction

PVE guest deletion removes per-VM ACLs even when guest purge is disabled. The initial storage attach on VM 9105 failed with `VM machine not found`: the UUID and VM ID were correct, but the CSI account could no longer see the replacement. The helper now idempotently restores the existing `Prototype105Disk` role for both the CSI user and privilege-separated token on `/vms/9105` during every ensure, before declaring worker readiness. No cluster-wide VM privileges are added.

The replacement also exposed DHCP becoming ready before the Talos maintenance API. Create/join now waits on a bounded read-only `talosctl version --insecure` probe before its single apply-config operation. It does not blindly replay a failed configuration write.

## Prepared environment

Use a distinct scratch namespace `prototype-runtime-storage` with the retained class from the earlier CSI proof. `volume-probe.py --namespace` permits this isolated claim without touching the older `prototype-worker-storage` data. Stop/release only the marker Pod before retiring its worker; leave PVC, PV and backend volume intact.

Run the explicit command with the observed name and UID:

```sh
PYTHONPATH=~/.local/share/homelab-capacity/source/src \
  ~/.local/share/homelab-capacity/venv/bin/python \
  ~/.local/share/homelab-capacity/retire.py --node OLD_NODE --uid OLD_UID
```

After retirement, independently verify that the backend volume still exists, no VM 9105 exists and its per-VM ACLs were removed. Restart the existing one-transition reconciler, submit the checked-in Kueue Job and verify that a different Kubernetes/hardware identity is created. Reattach the existing claim using `volume-probe.py verify`; verify marker, unchanged claim/PV/backend handle and exclusive attachment. This explicit probe release and submit step represents app orchestration and is separate from runtime worker retirement.

The regression suite covers disk ownership, running-VM refusal, foreign/stale node identities, reused IP with changed hardware identity, and lifecycle-lock contention. The live replacement cycle covers the ACL-loss bug at its actual boundary; command-level ACL tests alone do not prove it.

Live results and boundaries are recorded in [storage/evidence.md](storage/evidence.md).
