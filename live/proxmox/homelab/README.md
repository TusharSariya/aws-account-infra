# Proxmox homelab VM definitions

Implements OpenSpec task 3.1: declared VM hardware and identity, with locally tested plans. No VM creation or live API plan has been performed.

The deploy unit is `proxmox-homelab`, with inputs in `config/environments/proxmox/homelab/vms.tfvars`. It is excluded from cloud CI. Existing AWS deploy units and state keys are unchanged.

## Local validation

From the repository root:

```bash
./scripts/infra.sh proxmox-homelab init -backend=false
./scripts/infra.sh proxmox-homelab validate
tofu -chdir=live/proxmox/homelab test \
  -var-file=../../../config/environments/proxmox/homelab/vms.tfvars
```

The tests use OpenTofu's mock provider and `command = plan`: they do not access Proxmox, require credentials, or create infrastructure. Add `-verbose` to the test command to inspect the rendered plans. Provider schema validation runs separately with `validate`; mocked tests do not prove host/API compatibility.

OpenTofu 1.11.5 and `bpg/proxmox` 0.112.0 were used. Retain `.terraform.lock.hcl` in Git. Initial plugin installation succeeded with a warning that the publisher's signing key is expired and may be rejected by future OpenTofu versions. Resolve that upstream trust/bootstrap issue before claiming a clean-machine DR rehearsal has passed; do not disable signature verification.

## Initial hardware contract

| Guest | ID | vCPU | RAM (GiB) | Primary disks (GiB) | Reserved IPv4 | Startup order |
|---|---:|---:|---:|---|---|---:|
| talos-cp-01 | 100 | 2 | 4 | 100 | 10.42.0.220 | 1 |
| talos-worker-01 | 102 | 38 | 172 | 100 OS + 1200 data | 10.42.0.222 | 2 |

Primary disks total 1,400 GiB plus two EFI volumes, leaving approximately 395.992 GiB before auxiliary allocations. Guest RAM totals 176 GiB, leaving approximately 12 GiB of observed host RAM. These budgets must be measured under load; CPU affinity and NUMA tuning are deferred.

Both guests use OVMF, Q35, host CPU, VirtIO NICs on vmbr0, virtio-scsi-pci, raw local-lvm disks, disabled ballooning/hotplug/discard and no automatic reboot. Both enable the QEMU agent with trim disabled. Only the shared worker uses the qemu-plus-gVisor ISO. No NAS or sandbox VM is created. Worker scsi0 is its OS disk; scsi1 is its separate data disk, provisioned inside Talos in phase 6.

The IP fields document external DHCP reservations; the provider does not configure IPs inside a blank guest. Guest boot/lease verification remains separate. The disk boots before the ISO so an installed OS takes precedence; a blank disk falls through to its installer. ISO detachment is a later reviewed update.

`started` and `on_boot` default to false for the initial empty guests. Set the desired values explicitly in each guest input during the corresponding reviewed boot/startup task. Do not apply false values to an already running platform expecting OpenTofu to ignore them. `prevent_destroy` blocks normal planned replacement/deletion while this resource definition remains in configuration; it does not substitute for backups.

## Before live provisioning

The default `host_readiness_confirmed = false` precondition deliberately blocks live provisioning. The offline positive test bypasses this flag only under its mock provider. Do not set it for a real plan until:

- Network task 2.5 and recovery foundations 2.7/2.8 are satisfied.
- CPU/NUMA tuning is deferred and is no longer a creation prerequisite. No dedicated core or locality guarantee is implemented.
- Talos configuration and static checks in 3.3/3.4 are ready.
- Proxmox API permissions, independently recoverable credentials, trusted HTTPS connectivity through the laptop network and a recoverable state backend are configured. Environment variables `PROXMOX_VE_ENDPOINT` and `PROXMOX_VE_API_TOKEN` are supported by the provider; do not put credentials into tracked tfvars. TLS verification remains enabled.
- A current live storage/identity/ISO check and reviewed plan resolve all VM and disk targets.

No remote backend has been configured yet. Without an explicit backend, OpenTofu defaults to local state; `init -backend=false` is for validation only, not a durable recovery design. Configure and verify independent encrypted state recovery before the first real apply. Do not reuse AWS account/workload state keys. Preserve the reviewed configuration revision, lockfile, artifacts and state outside the failed homelab.

## Sources

- [Pinned provider VM schema and lifecycle behavior](https://github.com/bpg/terraform-provider-proxmox/blob/v0.112.0/docs/resources/virtual_environment_vm.md)
- [Pinned provider authentication and TLS configuration](https://github.com/bpg/terraform-provider-proxmox/blob/v0.112.0/docs/index.md)
- [OpenTofu test provider mocking](https://opentofu.org/docs/cli/commands/test/)
