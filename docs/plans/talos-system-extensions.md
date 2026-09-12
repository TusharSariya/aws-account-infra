# Talos System Extension Selection

## Status

Approved baseline for the initial Proxmox-hosted Talos build.

This document records the extension decision only. It does not assert that an
Image Factory schematic has been created, an ISO has been downloaded, or a VM
has been changed. Those results belong in the OpenSpec implementation log for
`build-talos-proxmox-homelab`.

In this document, **default** means the project's minimal approved extension
set. It does not mean the vanilla Talos Image Factory schematic, which contains
neither QEMU Guest Agent nor gVisor.

## Initial selection

Create two Talos v1.13.9, amd64 Image Factory schematics:

| Schematic | Nodes | Extensions |
|---|---|---|
| Control plane | `talos-cp-01` | `siderolabs/qemu-guest-agent` |
| Shared worker | `talos-worker-01` | `siderolabs/qemu-guest-agent`, `siderolabs/gvisor` |

No other system extensions are approved for the initial images.

### QEMU Guest Agent

Install `siderolabs/qemu-guest-agent` on every Talos VM. This allows Proxmox to
obtain guest information and request a coordinated guest shutdown.

Enable the QEMU Guest Agent option in Proxmox only for VMs installed from a
schematic containing this extension.

Talos v1.13.9 catalog reference resolved on 2026-08-25:

```text
ghcr.io/siderolabs/qemu-guest-agent:11.0.2@sha256:836e0221c066ac75e712830db8150a975c6ae5fec9d9a5e2cc8a10008e8d8b68
```

The similarly named `siderolabs/qemu` extension is a QEMU hypervisor and is not
required inside these Proxmox guests.

### gVisor

Install `siderolabs/gvisor` only on `talos-worker-01`. The control plane must not contain it. Trusted services and sandbox pods share the worker; only sandbox workloads must select this runtime.

Talos v1.13.9 catalog reference resolved on 2026-08-25:

```text
ghcr.io/siderolabs/gvisor:20260810.0@sha256:ed3a60380eef9d74ff0e44e8d4db87d309d608d891dce58c0d954eef89fce8be
```

Installing the extension makes the runtime available but does not enforce its
use. The sandbox implementation must also provide:

- A gVisor `RuntimeClass` using the Talos `runsc` handler.
- A shared-worker label without the obsolete sandbox-only `NoSchedule` taint.
- Admission policy requiring the runtime class and shared-worker node selector.
- Restricted Pod Security Admission and default-deny network policy.

Do not include `siderolabs/gvisor-debug` in the normal image. It may be added to
a disposable troubleshooting image when ordinary diagnostics are insufficient.

## Deferred extensions

These extensions require a demonstrated need before they are added:

| Extension | Adoption gate |
|---|---|
| `siderolabs/ecr-credential-provider` | The IAM Roles Anywhere and `aws_signing_helper` design passes a disposable-node proof without long-lived AWS credentials or static pull secrets. Install on workers that pull private ECR images, not automatically on the control plane. |
| `siderolabs/soci-snapshotter` | Large ECR-hosted images produce unacceptable measured cold-start times and the images have compatible SOCI indexes. |
| `siderolabs/stargz-snapshotter` | Lazy pulling of eStargz-formatted images is selected instead of SOCI after a measured comparison. Do not deploy both snapshotters by default. |
| `siderolabs/fuse3` | A selected CSI driver or approved workload explicitly requires host FUSE support. |
| `siderolabs/nut-client` | Talos nodes must react directly to a UPS instead of Proxmox coordinating guest shutdown through QEMU Guest Agent. |

## Explicitly excluded from the initial images

- `nfs-utils`: the extension supplies NFSv3 locking services; the simplified build uses worker-local storage.
- `iscsi-tools`, `drbd`, `zfs`, `btrfs`, and `nfsd`: storage is provided by the
  worker-local data volume on Proxmox disks. The design avoids distributed
  in-cluster storage on a single physical host.
- `intel-ucode` and physical NIC firmware or driver extensions: Proxmox owns
  the physical CPUs and NICs, so microcode, firmware, and hardware drivers are
  maintained on the Proxmox host.
- NVIDIA extensions: the GPU remains attached to the conventional Ubuntu GPU
  worker.
- `tailscale`: remote access should use the approved external subnet router or
  trusted management path instead of adding a daemon to every Talos node.
- `lldpd`: the Talos guests see VirtIO interfaces rather than the physical
  switch-facing NICs.
- `ctr`, `util-linux-tools`, and similar diagnostic tools: add them only to a
  disposable troubleshooting image when the Talos API cannot provide the
  required evidence.
- `cloudflared`: run the tunnel as a governed Kubernetes workload rather than
  as a host system extension.

## Removed NAS scope

The operator removed the Debian NAS VM on 2026-09-12. Previously acquired Debian artifacts are historical and unused by this build.

## Image Factory and audit requirements

For each schematic:

1. Select Talos v1.13.9 and amd64 in the official Image Factory.
2. Select exactly the extensions listed in the initial-selection table.
3. Record the schematic ID and canonical schematic body.
4. Download the `metal-amd64.iso` artifact.
5. Record the matching `factory.talos.dev/installer` image reference.
6. Configure the Talos machine installation to use the installer image from
   the same schematic as the boot ISO.
7. Compute and record the locally stored ISO digest.
8. After installation, verify the effective extensions with
   `talosctl get extensions` before accepting the node.

Extension references must remain pinned by digest. If the Talos version
changes, resolve compatible extension references from that version's catalog
and create a reviewed replacement schematic rather than reusing these v1.13.9
references.

## References

- [Talos system extensions](https://github.com/siderolabs/extensions)
- [Talos Image Factory](https://docs.siderolabs.com/talos/v1.13/learn-more/image-factory)
- [Talos on Proxmox](https://docs.siderolabs.com/talos/v1.13/platform-specific-installations/virtualized-platforms/proxmox)
- [Talos Kubernetes rebuild plan](talos-kubernetes-rebuild.md)
- [Authorized agent NAS plan](authorized-agent-nas.md)
