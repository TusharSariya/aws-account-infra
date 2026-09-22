# Main Talos VM relocation tooling

Use the [ordered migration runbook](../../docs/runbooks/main-control-plane.md).
The laptop is authoritative after the recorded destination launch. The source is
stopped and protected; never boot its stale disk without a latest-state reverse migration.
These helpers never bootstrap a replacement cluster.

- `prepare-wizard.sh`: the one interactive sudo entry point; copies reviewed
  root-owned helpers/services, KVM access and sleep prevention. Repeat after
  reviewing a changed privileged helper. It does not stop a cluster.
- `ops.sh`: bounded privileged operations; no caller-supplied paths or shell text.
- `network.py`: isolated TAP/bridge, host routing, exact Wi-Fi proxy neighbours,
  scoped coexistence with the pilot firewall, teardown, reboot state and reconnect.
- `firmware-probe.py`: tests source pflash on laptop QEMU without cluster disks/NICs.
- `migrate.py`: private capture, graceful pilot retirement, offline source copy,
  checksums, source fence and destination launch. A journal prevents unsafe repeats.
- `capacity.py`: samples laptop and CP memory/swap reserves.
- `maintenance.py`: persistent private desired-state journal, volume identity and shutdown blockers.
- `platform-state.py`: explicit ordered platform stop/restore, without host power control.
- `resume-submissions.py`: restore saved schedule and runner fields after recovery.
- `verify-independence.py`: owned CP probe for API, etcd and cluster DNS checks.
- `recovery-wizard.sh`: one operator-started Wi-Fi/reboot test after both hosts are off; requires interactive sudo.

`systemd/` uses fixed installed paths. The VM runs as `tushar` with the KVM group;
network operations run as root. Shutdown requests ACPI through QMP and disables
forced killing. A failed guest shutdown requires operator investigation, not a
forced power-off or live disk copy. Real route activation requires source fencing.
The NetworkManager dispatcher reasserts exact routes/proxy neighbours on Wi-Fi up;
reboot discards stale kernel-object handles by comparing the saved boot ID.

Local checks:

```sh
python3 -m unittest discover -s platform/main-control-plane/tests -v
python3 kubernetes/platform/main/validate.py
uvx ruff@0.12.12 check platform/main-control-plane kubernetes/platform/main --exclude vendor
uvx ruff@0.12.12 format --check platform/main-control-plane kubernetes/platform/main --exclude vendor
shellcheck platform/main-control-plane/ops.sh platform/main-control-plane/launch.sh platform/main-control-plane/prepare-host.sh platform/main-control-plane/90-main-control-plane
```

Private prerequisites belong under `~/.local/share/main-control-plane/private`
and never in this directory. Before cutover keep independent recovery copies and
verify direct management access. See the runbook for exact source VM/disk geometry,
acceptance gates and latest-state reverse migration.
