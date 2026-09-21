# Create the pilot VM and restore its cluster

This repository holds the VM recipe, pinned public downloads, monitoring manifests,
Argo core installation and recovery commands. Git preserves this recipe, not the
cluster state. Private recovery material stays outside Git; no VM image upload or
VM archive is included.

The supported recovery target is this existing cluster: guest `10.0.2.15`, MAC
`52:54:00:77:03:01`, control-plane hostname `talos-v93-t3u`, and kube-system UID
`507117e6-f7ed-4307-a016-4ecc9a28b519`. Restoring requires a private state backup.
Do not generate new Talos secrets when restoring it. An independently generated
cluster would need new worker enrollment and updated pilot identity checks.

## What is reproducible, and what must be backed up

| Item | Source / recovery method |
| --- | --- |
| 3-vCPU, 6-GiB QEMU VM; 24-GiB system disk; 8-GiB monitoring disk | `prepare_disks.py`, `launch.sh`, `artifacts.json` |
| Talos v1.13.9 ISO and CLI, Kubernetes v1.36.3 CLI | Public downloads checked against pinned SHA-256 values |
| Bridge, TAP, guest DHCP reservation and forwarding | `network-import.sh`; host address, username and uplink are inputs |
| Kubernetes objects, Secrets, Cilium and controller configuration | Private etcd snapshot |
| Cluster identity, signing keys and node configuration | Private current machine configuration and client credentials |
| Monitoring configuration and Argo core | `../monitoring/kubernetes` and `../argocd` |
| Prometheus/Loki/Grafana/Alloy/Alertmanager volume contents | Separate volume backup; absent that, history is lost and monitoring starts empty |
| Existing storage-proof and worker-local data | Their own backups or surviving worker disks; never reformat these |
| Ubuntu lifecycle controllers and provider credentials | Separate host recovery material; see the host-specific instructions below |

An etcd snapshot saves Kubernetes metadata and Secrets, **not PVC file contents**.
Instructions and empty disks cannot recover missing state. Recovery is bounded by
the age of the snapshot and each volume's own backup.

## Capture private recovery state

On the running source, with the repository staged at `~/pilot-platform`:

```sh
python3 ~/pilot-platform/vm/recovery.py backup \
  "$HOME/pilot-recovery-$(date -u +%Y%m%dT%H%M%SZ)"
python3 ~/pilot-platform/vm/recovery.py check "$HOME/pilot-recovery-TIMESTAMP"
```

The helper checks the cluster identity and writes a consistent etcd snapshot,
the complete current Talos machine configuration, talosconfig, kubeconfig,
host-monitoring credentials, node/PV inventories and checksums. It creates a new
0700 directory with 0600 files outside Git. It neither shuts down the VM nor
includes virtual disks, creates an archive, or uploads anything.

The directory contains administrative secrets. A copy left only on the laptop does
not protect against losing that laptop. Place a verified encrypted copy in a chosen
private backup location before relying on disaster recovery. That off-host location
has not been selected or populated as part of this local-only work.

Keep separate backups of `~/.local/share/homelab-capacity`, its source/virtualenv
rebuild instructions, `~/.config/homelab-capacity`, and the four lifecycle user
service definitions. Include provider credentials, both slot states and maintenance
markers. Record which services were active. Keep `~/.local/share/pilot-monitoring`
and its user units if host monitoring remains the accepted rollback configuration.
Do not assume these host-specific services are recreated by the VM recipe.

## Prepare replacement hardware without starting a second cluster

Use an x86-64 Linux host with KVM, three schedulable vCPUs, 6 GiB guest RAM plus
at least 512 MiB available host memory under load, and space for 32 GiB of virtual
disk growth. Install QEMU, Python 3.12+, OpenSSL, iproute2, dnsmasq, nftables, ACL
and udev tools. QEMU/Talos must support virtio-balloon free-page reporting.

The original control plane must be stopped or conclusively unavailable before a
replacement uses its address and identity. **Only one copy may run at a time.**
Pause the source lifecycle services and preserve the secondary's maintenance marker.
Do not power on or reconfigure the paused secondary as part of this recovery.

Prepare disks in a **new, nonexistent directory outside Git**:

```sh
export PILOT_SOURCE="$HOME/pilot-platform"
export PILOT_VM_DIR="$HOME/talos-wifi-prototype"
python3 "$PILOT_SOURCE/vm/prepare_disks.py" "$PILOT_VM_DIR"
# Optional alternative: --artifact-cache /path/to/verified-public-artifacts
python3 "$PILOT_SOURCE/vm/prepare_disks.py" "$PILOT_VM_DIR" --check-artifacts
```

The helper refuses an existing directory, including the running source directory.
It downloads and checks pinned public artifacts, creates sparse qcow2 disks,
checks their consistency, and copies launch/network files. It does not boot anything.
If preparation fails, inspect the new partial directory; it is never reused or
removed automatically. On the existing source, use `migrate.py` recovery paths;
never run disk creation over its current files.

Review the destination firewall, then run the narrow network helper interactively:

```sh
sudo bash "$PILOT_VM_DIR/network-import.sh" DESTINATION_USERNAME UPLINK_INTERFACE HOST_IPV4
```

It requires the destination user's private primary group and creates a temporary
KVM ACL, bridge/TAP and named nftables rules. An existing host firewall may need
matching allow rules. It retains the current worker/client LAN `10.0.0.0/24`;
a different LAN needs a routing review. Update worker/router/client routes for
`10.0.2.0/24` to the new host's IPv4 address, with return routes and Talos, Kubernetes
API and Cilium connectivity. Do not change the guest address or MAC.

## Restore the existing cluster onto the empty system disk

Set `RECOVERY` to the verified private backup. Work on the replacement host only.
Keep the original source offline and host lifecycle automation paused throughout.

```sh
export RECOVERY="$HOME/pilot-recovery-TIMESTAMP"
umask 077
python3 "$PILOT_SOURCE/vm/recovery.py" check "$RECOVERY"
mkdir -m 700 "$PILOT_VM_DIR/private"
cp "$RECOVERY/talosconfig" "$PILOT_VM_DIR/private/talosconfig"
cp "$RECOVERY/kubeconfig" "$PILOT_VM_DIR/private/kubeconfig"
cp "$RECOVERY/controlplane.machineconfig.yaml" "$PILOT_VM_DIR/private/restore.machineconfig.yaml"
cd "$PILOT_VM_DIR"
```

Pin the restored hostname so local-PV affinity and serving-certificate checks still
refer to the same management node. Do not edit the secret material:

```sh
# This pilot's saved config has a HostnameConfig with auto: stable.
./talosctl machineconfig patch private/restore.machineconfig.yaml \
  --patch '{"apiVersion":"v1alpha1","kind":"HostnameConfig","$patch":"delete"}' \
  -o private/no-hostname.machineconfig.yaml
cat > private/restore-hostname.yaml <<'PATCH'
apiVersion: v1alpha1
kind: HostnameConfig
hostname: talos-v93-t3u
PATCH
./talosctl machineconfig patch private/no-hostname.machineconfig.yaml \
  --patch @private/restore-hostname.yaml -o private/restored.machineconfig.yaml
./talosctl validate --config private/restored.machineconfig.yaml --mode metal
```

For **these newly prepared empty disks only**, derive a one-time installer boot
from the versioned launch command. Subsequent boots always use `launch.sh`:

```sh
test -f UNCONFIGURED
sed -e 's/-boot order=c/-boot order=c,once=d/' \
  -e 's/,bootindex=1//' launch.sh > first-boot.sh
bash first-boot.sh
./talosctl apply-config --insecure --nodes 10.0.2.15 \
  --file private/restored.machineconfig.yaml
```

Wait for installation and reboot. Use the saved trusted credentials from now on;
`--insecure` is only for the new, unconfigured maintenance-mode node. When etcd is
in `Preparing`, restore the snapshot instead of bootstrapping an empty database:

```sh
./talosctl --talosconfig private/talosconfig -e 10.0.2.15 -n 10.0.2.15 service etcd
./talosctl --talosconfig private/talosconfig -e 10.0.2.15 -n 10.0.2.15 \
  bootstrap --recover-from="$RECOVERY/etcd.snapshot"
./kubectl --kubeconfig private/kubeconfig get namespace kube-system \
  -o jsonpath='{.metadata.uid}{"\n"}'
./kubectl --kubeconfig private/kubeconfig get nodes
```

The UID must match the recovery manifest and the pilot identity above. A new disk
may change node system UUID, but the node name, PKI and Kubernetes object identity
must be verified. If client configs contain old absolute paths, adjust only those
file paths. Scripts assume `~/talos-wifi-prototype` and the existing pilot profile;
update the local profile if using another destination directory or username.

If the snapshot contains monitoring PVCs but the monitoring disk is new, first
scale `pilot-monitoring` Deployments to zero, then apply `user-volumes.yaml` and
verify all five `u-pilot-*` volumes are ready before restoring replicas. Empty
monitoring volumes mean lost history, not a successful data restore. If retaining
volume data is required, restore its separate backup before starting the Pods.
Do not delete retained PVCs/PVs or touch worker storage-proof volumes. An etcd
snapshot captured during rollback may have monitoring scaled to zero already.

Restore host-specific lifecycle state and provider access separately before starting
the exporter. On the destination, the recovery-only helper checks that the saved
TLS certificate/token match the restored Kubernetes Secret, rebases the restricted
reader's local paths, renews it if needed, and installs only the exporter and the
five localhost forwards:

```sh
python3 "$PILOT_SOURCE/monitoring/kubernetes/restore_host.py" \
  "$RECOVERY/host-monitoring-private"
# Interactively, if persistent user services are needed after SSH logout:
sudo loginctl enable-linger DESTINATION_USERNAME
```

It refuses an existing host private directory. Do not run the migration installer
or manufacture a resize checkpoint on a fresh replacement host. Check
`kubelet_tls.py` for pending serving CSRs. For lifecycle services, only one set of reconcilers may run. Resume only previously active units
once worker, controller and storage identities are verified, preserving pause state.
Remove `UNCONFIGURED` after successful recovery. Run `monitoring/measure.py` and
`monitoring/acceptance.py` log, dashboard and alert checks. Check the Argo capacity
gate before installing Argo if absent from the snapshot. On a restored host, verify
Pod replacement and a graceful shutdown/restart with `launch.sh`, preserving the
previously active lifecycle units and checking the saved node/PV identities and
historical log/metric queries afterward. The source migration's `kubernetes/accept.py`
restart automation requires its original migration checkpoint and `boot.sh`; do not
run it on a fresh replacement or manufacture those files to bypass its checks.
Require at least 512 MiB available on both host and guest, no sustained swapping,
healthy controllers and no monitoring OOMs before declaring recovery done.

## Validation status

Publisher checksums were verified for all three artifacts. Real qcow2 creation and
24-GiB/8-GiB geometry were tested using synthetic artifact fixtures; no guest was
booted. The complete saved configuration was patched to the static hostname and
passed Talos v1.13.9 validation in metal mode. A local private recovery backup was
created and its checksums verified. The final backup is on the source laptop at
`~/pilot-recovery-20260921T232957Z`, after accepted monitoring and Argo removal.
Full fresh-disk/etcd recovery needs a separate isolated drill;
it has not been proven by a normal VM restart. No cross-host restore is claimed.
The current rollout result is recorded in
[the verification report](../monitoring/evidence/portable-preflight.md).

Sources: [Talos disaster recovery](https://docs.siderolabs.com/talos/v1.13/build-and-extend-talos/cluster-operations-and-maintenance/disaster-recovery),
[Talos release artifacts](https://github.com/siderolabs/talos/releases/tag/v1.13.9),
and [user-volume lifecycle](https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/storage-and-disk-management/disk-management/user).
