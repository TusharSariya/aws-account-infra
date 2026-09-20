# Disposable-worker storage prototype

Question: does a separately owned data volume survive deleting a disposable Talos worker and reattach to a new worker identity on the same PVE host?

Status2026-09-20: preparation only. Neither a CSI installation nor a live create/delete/reattach test has run. The Mac currently has192.168.50.189 while prior laptop/PVE addresses are10.0.0.181/.223. Both SSH attempts timed out, as did the known primary PVE Tailscale path100.101.182.9. GitHub API also timed out. Do not interpret these failures as evidence that the hosts are off or have new addresses.

GitHub issues are the canonical planning tracker. Markdown contains linked design, research and prototype evidence, not a replacement local issue tracker. Pending decisions/evidence must be synchronized when GitHub access returns.

## Prepared probe

volume-probe.py renders or runs a1GiB retained-volume marker test only against the named laptop-wifi-PROTOTYPE cluster at10.0.2.15. It requires a verified Proxmox CSI StorageClass with Retain policy. It never deletes a VM, PVC, PV or backend volume. It records PVC/PV identities and the backend handle; verification refuses another volume or the original node identity.

On the laptop after prerequisites are established:

```bash
cd ~/talos-wifi-prototype
python3 volume-probe.py create --node TEST_WORKER --storage-class VERIFIED_TEST_CLASS
python3 volume-probe.py release --node TEST_WORKER --storage-class VERIFIED_TEST_CLASS
# Separately verify CSI detach AND all guest disk references using installed PVE APIs.
# Only then exercise scoped test-worker deletion and replacement provisioning.
python3 volume-probe.py verify --node REPLACEMENT_WORKER --storage-class VERIFIED_TEST_CLASS
```

Replace the uppercase names with observed prototype resources. A missing CSI/storage prerequisite is a stop, not a reason to substitute production local-path storage. A test Pod deletion does not by itself prove that backend detachment has completed. No VM deletion script is supplied before exact installed PVE/CSI ownership and delete semantics are verified.

Read-only next steps after access is restored: confirm secondary PVE identity and VM9103 ownership, current prototype cluster identity, PVE version/cluster status, installed API disk semantics, driver prerequisites, distinct endpoint regions and capacity. Then install scoped prototype CSI configuration, validate/render manifests against its API, and perform the ordinary volume lifecycle proof. Existing production VM103 and primary data disk remain excluded.

Validation performed locally: Python compilation and JSON manifest rendering. No live admission, attachment, deletion, storage persistence or autoscaling result is claimed. This is the storage subproof; Kueue/Cluster Autoscaler provisioning remains a separate unfinished part of the authorized prototype.
