## Why

The repository's Ansible automation describes a retired Ubuntu/kubeadm and workstation-management path that no longer matches the Talos/OpenTofu/Helm operating model. Keeping it active creates misleading runbooks, unnecessary CI, and continued custody of encrypted legacy configuration in the working tree.

## What Changes

- **BREAKING**: Remove the complete tracked `ansible/` implementation, including server, workstation, Homebrew, MLX, inventory, and Vault tooling.
- Preserve the committed Vault ciphertext privately with restricted permissions and a verified SHA-256 digest before removal; leave the separate Vault password untouched.
- Replace the Ansible workflow with a shell-only workflow that retains existing ShellCheck and Bats coverage, fork restrictions, and default runner behavior.
- Remove the Ansible change-detection scope and update its focused tests for the renamed shell workflow.
- Update current repository guidance to use Talos, OpenTofu, and Helm and explicitly defer laptop bootstrap automation.
- Remove the Vault runbook and identify retained Ubuntu/kubeadm-era documents as historical, linking deleted sources to the pre-removal revision.
- Retain standalone server and recovery scripts and their tests.

## Capabilities

### New Capabilities

- `repository-automation-boundaries`: Defines the active server-management path, shell validation behavior, historical-document treatment, and safe retirement of tracked Ansible material.

### Modified Capabilities

None.

## Impact

This changes repository automation, CI configuration, documentation, and legacy encrypted material only. It does not change application APIs, deployment roots, runtime configuration, GitHub protection rules, installed software, running servers, Talos VMs, Kubernetes services, credentials, or the existing OpenTofu and Helm management paths.
