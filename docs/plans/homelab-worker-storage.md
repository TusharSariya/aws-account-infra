# Worker data-volume foundation

The worker's versioned Talos patch provisions one XFS partition on its separate
1,200-GiB Proxmox scsi1 disk. The selector requires /dev/sdb, exact disk size,
the stable QEMU scsi1 by-id link and !system_disk. The 100-GiB scsi0 OS disk is
excluded. The partition consumes available disk space (at least 1,199 GiB,
allowing GPT overhead); automatic later growth is disabled.

Talos mounts u-local-path-provisioner at /var/mnt/local-path-provisioner and
propagates user-volume mounts into kubelet. No extra bind mount is required.
This prepares the filesystem for task 6.3, which installs the local-path
provisioner and defines StorageClasses/PVC behavior. No application capacity
quota or application-data backup is provided by this filesystem alone.

## Apply and acceptance

1. Change the worker patch through a reviewed PR. CI runs scripts/talos-ci.py:
   strict Talos validation, exact configuration guard, authenticated disk inventory
   and dry-run, then the existing guarded OpenTofu plan.
2. Before applying, require a blank data disk or the one expected existing XFS
   partition. Unknown contents, a missing/changed disk identity or a duplicate
   user-volume label fail closed. Do not wipe or bypass this check to proceed.
3. Use the existing apply-label CI workflow. Talos performs allocation, formatting
   and mounting through its machine-configuration resource. No local config apply.
4. CI checks ready VolumeStatus and MountStatus on /dev/sdb1. Only when preflight
   found a blank data disk, it performs a worker-only firmware reboot with
   talosctl reboot --mode=powercycle --wait --timeout=8m. It compares OS/data
   partition and filesystem UUIDs, checks the remount and runs Cilium network
   acceptance. Later applies against existing storage do not automatically reboot.
   A failed reboot is not followed by a reset or forced retry.

Read-only inspection, with the restored private TALOSCONFIG environment set:

```bash
talosctl -n 10.42.0.222 get disks sdb -o yaml
talosctl -n 10.42.0.222 get discoveredvolumes sdb1 -o yaml
talosctl -n 10.42.0.222 get volumestatus u-local-path-provisioner -o yaml
talosctl -n 10.42.0.222 get mountstatus u-local-path-provisioner -o yaml
```

## Recovery

Restore the original Talos identity independently, reconstruct the two VMs from
the Proxmox root, and apply the versioned worker configuration through Talos CI.
A new blank matching disk is provisioned; an existing matching labeled partition
is reused. Removing a UserVolumeConfig unmounts it; it does not erase the data.
Preserve the volume name and disk identity when recovering existing storage.
Never change the install disk to /dev/sdb, run wipe as rollback, or replace a
populated disk without an independent verified application-data backup.

Daily etcd backups include configuration inputs, not the files on this disk.
Task 6.4 must supply application-consistent off-host backups before treating
worker data as independently recoverable.

References: [Talos user volumes](https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/storage-and-disk-management/disk-management/user),
[disk selectors](https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/storage-and-disk-management/disk-management/common).
