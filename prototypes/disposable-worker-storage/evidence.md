# Storage lifecycle evidence: 2026-09-20

Verdict: **PASS for ordinary same-host replacement with separately owned retained storage.**

Environment: isolated laptop Talos1.13.9 / Kubernetes1.36.3 cluster; standalone secondary PVE9.2.2; Proxmox CSI chart0.5.12 / driver0.20.0. TLS verification enabled. No Proxmox cluster conversion was needed for this tested path.

| Identity | Before and after |
| --- | --- |
| PVC UID | `299d7519-cd4e-4aed-9d97-6a8349581594` |
| PV | `pvc-299d7519-cd4e-4aed-9d97-6a8349581594` |
| PV UID | `9d7bc34c-c835-4e82-a625-329153a5f839` |
| CSI handle | `prototype-secondary/pve/local-lvm/vm-9199-pvc-299d7519-cd4e-4aed-9d97-6a8349581594` |
| Marker | `prototype-ee64398e5c5ca62d53d165cf6fbde282` |
| Capacity | 1,073,741,824 bytes |

Observed sequence:

1. Provisioned the scratch PVC and wrote/synced/read the marker on VM9103 (`talos-86j-vvl`, `10.0.0.6`).
2. Deleted only the probe Pod. Confirmed zero VolumeAttachments and no retained-volume reference anywhere in VM9103 config, including unused disks.
3. Drained the old node, completed a Talos shutdown and confirmed PVE stopped status. The deletion guard accepted only `vm-9103-disk-0` and `vm-9103-disk-1` as disposable disks.
4. Destroyed VM9103. PVE reported both disposable logical volumes removed. The separately owned `vm-9199-pvc-...` volume remained. A later `pvesm list local-lvm --vmid 9103` was empty.
5. Created VM9104 with fresh 24GiB OS storage and a distinct SMBIOS UUID, installed Talos from ISO and joined as `talos-5wk-ckr` (`10.0.0.8`). Set provider ID `proxmox://prototype-secondary/9104` and the test topology/plugin labels.
6. Recreated only the probe Pod against the original PVC. The probe checked unchanged PVC/PV UIDs and backend handle, refused the old node identity, and read the exact original marker. Its result was `marker verified`, `replacement: true`.
7. Confirmed VolumeAttachment true on the replacement, PVE `scsi1` referencing the same owner9199 volume, probe Pod1/1, CSI controller5/5 and node plugin3/3, and both prototype nodes Ready. All three production nodes were also Ready during the test.

The first replacement attach attempt waited for the new CSI node plugin to register while images pulled; it subsequently attached without intervention. Node Ready alone is therefore not sufficient evidence that storage is ready.

Retained test resources: replacement VM9104, owner9199 scratch data volume, PVC/PV and marker Pod, isolated CSI release/credentials, and the temporary secondary return route. These support follow-on integration; teardown boundaries are in README.md. The old VM9103 and its disks are gone.

Limitations: one ordinary lifecycle, one secondary host, one1GiB ext4 volume, manual orchestration and topology/provider-ID assignment. This is not a restore/failure drill, cross-host data mobility proof, template-clone proof, production migration, or a working Kueue/Cluster Autoscaler/IMM2 pipeline. Worker deletion must continue to be gated on successful drain and confirmed storage detachment; any retained data reference blocks VM destruction.
