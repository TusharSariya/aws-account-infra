## Why
GitHub-hosted runner minutes are exhausted. Execute CI on existing hardware while retaining GitHub orchestration and protected merge gates.

## What Changes
- Add a 4-vCPU, 16-GiB, 100-GiB Linux CI manager VM outside Talos.
- Reduce worker RAM to 156 GiB while retaining its CPU and disks.
- Run one disposable nested KVM guest per GitHub job, with private manager credentials and isolated networking.
- Migrate all workflows, including ARM packaging through emulation, retaining protected deployment and acceptance.

## Capabilities
### New Capabilities
- `homelab-self-hosted-ci`: reproducible isolated on-premises GitHub execution.
### Modified Capabilities
None. Existing lifecycle requirements remain applicable.

## Impact
Proxmox OpenTofu, Ansible, DHCP and Tailscale policy, runner manager, workflow routing, acceptance and operational documentation. Three ordered PRs: foundation, runner management, workflow migration. The existing AI review stack remains separate.
