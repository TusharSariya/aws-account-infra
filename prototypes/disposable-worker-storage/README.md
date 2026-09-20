# Disposable-worker storage prototype

Question: does a separately owned data volume survive deleting a disposable Talos worker and reattach to a new worker identity on the same PVE host?

This is throwaway code for [issue #105](https://github.com/TusharSariyaOrg/aws-account-infra/issues/105), restricted to the isolated `laptop-wifi-PROTOTYPE` cluster. GitHub issues are the canonical planning tracker; this directory records the implementation and evidence.

## Result: passed on 2026-09-20

The old worker was drained, stopped and deleted with both of its disposable OS disks. The independently owned 1GiB data volume survived. Fresh VM9104 joined as `talos-5wk-ckr` at `10.0.0.8`; the original PVC and PV UIDs and volume handle remained unchanged, and the marker matched after reattachment. See [evidence.md](evidence.md).

## Scope and ownership

The laptop hosts the prototype control plane at `10.0.2.15`. Secondary PVE (`10.0.0.223`, standalone, node name `pve`) hosts the disposable workers. Production VM103 and all primary-host data are excluded.

- Old worker: VM9103, `PROTOTYPE-wifi-peer`, node `talos-86j-vvl`.
- Replacement: VM9104, `PROTOTYPE-storage-replacement`, a fresh 24GiB OS disk, 2 vCPU and 4GiB RAM, no autostart.
- Data owner: reserved ID9199, separate from both worker IDs; no VM9199 is required.
- Test PVC: `prototype-worker-storage/retained-marker`, 1GiB, `Retain` policy, driver lifecycle `keep`.

The fresh worker is installed from the Talos ISO. This does not test template cloning, a Cluster Autoscaler adapter, Kueue admission, physical power control, cross-host volume movement or production migration.

## CSI setup

`csi-values.yaml` pins driver v0.20.0 images for chart `proxmox-csi-plugin` 0.5.12. The controller runs on the laptop control plane; the node plugin selects only workers labeled `prototype.homelab/csi-worker=true`. Each worker also needs region `prototype-secondary`, zone `pve`, and provider ID `proxmox://prototype-secondary/VMID`.

The cloud-config Secret `prototype105-proxmox` is supplied outside Git. Its `features.controllerVmID` is 9199. The PVE endpoint is `https://pve.proxmox.local:8006/api2/json`; a host alias resolves it to the secondary address, and Secret `prototype105-pve-ca` supplies the PVE CA. TLS verification stays enabled.

Temporary PVE user `prototype105-csi@pve` and privilege-separated token `csi` have matching user/token ACLs:

- `Prototype105Disk`: `VM.Audit VM.Config.Disk` on `/vms/9103`, `/vms/9104`, `/vms/9199`.
- `Prototype105Storage`: `Datastore.Audit Datastore.AllocateSpace` on `/storage/local-lvm`.

The datastore permission covers the storage, not a volume-name prefix. The token has no VM power, clone or allocation permission. A temporary secondary-host route `10.0.2.15/32 via 10.0.0.181 dev vmbr0` returns CSI API traffic to the laptop. No production cluster CSI installation or primary-host route change is involved.

## Run the probe

On the laptop, with pinned `kubectl`, prototype credentials in `private/` and the CSI release ready:

```bash
cd ~/talos-wifi-prototype
python3 volume-probe.py create --node OLD_NODE --storage-class prototype105-retain
python3 volume-probe.py release --node OLD_NODE --storage-class prototype105-retain
```

`create` writes a random marker and records PVC UID, PV UID and volume handle in `private/storage-probe.json`. `release` deletes only the test Pod. Wait for the VolumeAttachment to disappear and inspect the PVE VM config: neither an attached nor an unused disk reference may point to retained data. Drain and cleanly stop the old worker.

On secondary PVE only, invoke `peer-lifecycle.py inspect-delete --retained-volume VOLUME_ID`, then `delete-old` with the same argument. The helper accepts only old VM9103 with the expected name, stopped state and its own disposable disk references. Any foreign disk reference blocks deletion. It verifies that the separately owned volume still exists after deletion. `create-new` creates VM9104 only if that ID is absent.

Remove the old Kubernetes Node after deletion, install the replacement using the isolated worker configuration, verify its fresh identity, and set its provider ID and topology/plugin labels. Then run on the laptop:

```bash
python3 volume-probe.py verify --node NEW_NODE --storage-class prototype105-retain
```

Verification requires the original PVC/PV identities and backend handle, a different node identity, and the original marker contents. Neither probe action deletes the PVC, PV or backend volume.

## Teardown boundary

Retained resources are intentionally left for subsequent prototype work. To tear down later: delete the probe Pod, wait for detach, remove the replacement VM only after checking all disk references, then explicitly remove the scratch PVC/PV and its separately owned backend volume. `Retain` does not clean the backend automatically. Uninstall the CSI release and its namespace/secrets; remove the test user/token, ACLs and roles; delete only the exact temporary host route above. Remove private token copies on the Mac and secondary PVE. Keep the laptop control-plane prototype unless its separate teardown is authorized.

Never run the old-worker deletion helper against the replacement: its fixed IDs deliberately prevent that reuse.
