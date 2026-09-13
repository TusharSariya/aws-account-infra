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


## Kubernetes claims (task 6.3)

OpenTofu manages two Helm releases: a local policy chart for namespaces, classes
and request budgets, and the checksum-verified upstream local-path-provisioner
0.0.37 chart. Controller and helper images are pinned by digest. The provisioner
and its hostPath helper pods use the dedicated local-path-storage namespace;
that namespace allows the hostPath operation. Ordinary applications receive PVCs
and do not require privileged access or Talos credentials.

Both classes use WaitForFirstConsumer and worker hostname topology. There is no
default class and no automatic PVC expansion. Choose worker-local-retain for
models and durable application files. Deleting its PVC leaves the PV Released
and files in place for deliberate recovery/rebinding or cleanup. Choose
worker-local-delete only for disposable scratch data: deleting the claim
removes the underlying directory. Retain is not an off-host backup.

| Namespace | Total requested storage | Maximum per PVC | Maximum claims |
| --- | --- | --- | --- |
| homelab-models | 800 GiB | 800 GiB | 10 |
| homelab-services | 100 GiB | 100 GiB | 10 |
| homelab-data | 100 GiB | 100 GiB | 10 |

Minimum claim size is 1 GiB. These are initial admission budgets, not preallocated
partitions or filesystem write quotas. Local-path ignores requested volume sizes
when applications write data; it does not provide a hard byte limit. Other
namespaces are not covered by these quotas. Released Retain volumes also consume
space after their claims stop counting toward quota. Actual usage monitoring and
retained-volume accounting remain necessary; task 6.5 provides monitoring.
Change these budgets through the policy chart in a PR, keeping total requested
capacity below the filesystem size with headroom. Important model files, broker
state and databases still require application-aware backups under task 6.4.

Example claim (application repository):

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: model-files
  namespace: homelab-models
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: worker-local-retain
  resources:
    requests:
      storage: 100Gi
```

Pending is expected until a consuming pod is scheduled. Mount this claim in the
pod via persistentVolumeClaim. The volume is tied to talos-worker-01; losing that
worker does not move data to another node. Recreate a pod against the same PVC
to preserve files. For a Released Retain volume, inspect the original claim and
path, back up its files, and explicitly prebind a replacement claim to that PV;
never clear claimRef on an unrelated or still-bound volume.

CI runs scripts/homelab-storage-validate.py after each apply. It verifies the
live class/namespace budgets, uses disposable restricted test pods to write and
reread a random proof across recreation, checks worker/data-path affinity,
confirms Retain keeps files after PVC deletion, and checks Delete removes the
PV. Its cleanup changes reclaim policy only on volumes matched to newly-created
test claim UIDs. It never changes application PV reclaim policies. The local-path
setup/teardown scripts reject the wrong path or a missing data filesystem mount
so a failed mount cannot silently put new volumes on the OS disk.

Source: [upstream 0.0.37](https://github.com/rancher/local-path-provisioner/tree/v0.0.37),
[Kubernetes storage quotas](https://kubernetes.io/docs/concepts/policy/resource-quotas/#storage-resource-quota).
