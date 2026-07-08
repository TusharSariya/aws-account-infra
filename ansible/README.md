# Environment configuration with Ansible

Ansible manages the macOS administration/MLX host and an upstream Kubernetes
cluster built with kubeadm. Cluster actions are deliberately staged; no playbook
removes K3s, erases disks, or automatically reboots a host.

## Architecture

- Ubuntu desktop: single schedulable control plane, local storage, and NVIDIA GPU.
- Old Ubuntu laptop: tainted worker for explicitly selected lightweight workloads.
- Optional Multipass VM: tainted ARM64 worker with bridged LAN networking.
- Mac: Ansible, cluster CLIs, container development, and native MLX inference.

The cluster is not highly available. If the desktop or its etcd data is lost, the
API is unavailable and the cluster may need to be restored or rebuilt.

## Bootstrap the controller

From the repository root:

```bash
ansible-galaxy collection install -r ansible/requirements.yml
ansible-playbook ansible/playbooks/workstation.yml --check --diff
ansible-playbook ansible/playbooks/workstation.yml
```

Homebrew packages are managed by the `homebrew` role (macOS only). It declares the
machine's formulae, casks, and taps in `roles/homebrew/files/Brewfile.{base,dev,ops}`
(select which apply per host with `homebrew_bundles`) and drives them with `brew bundle`.
The role is **additive**: it installs anything declared-but-missing and, on every run,
**warns** about anything installed-but-undeclared ("add these to a Brewfile") — it never
removes packages. Seed or refresh the Brewfiles with `brew bundle dump`. `--no-upgrade`
keeps runs non-disruptive; upgrade deliberately with `brew upgrade`.

The `admin_workstation` role then installs the version-pinned tooling that isn't a plain
brew package: pyenv-adjacent SDKMAN, tenv-pinned Terraform/OpenTofu, and the pinned
helm-diff plugin (`helm`, `tenv`, etc. come from the `homebrew` role, which runs first).
MLX uses a dedicated pyenv virtual environment; Conda is not required for MLX and remains
available for projects that need it.

## Configure inventory

Copy `inventories/example` to the ignored `inventories/local` directory. Configure:

- stable addresses for every physical and virtual node;
- exactly one host in `kubernetes_control_plane`;
- workers and their capability groups;
- `kubernetes_api_endpoint`, which must remain stable;
- an unused MetalLB range outside the router's DHCP pool.

Keep passwords, tokens, kubeconfigs, and private values in Ansible Vault or SOPS.
The example addresses intentionally fail preflight checks.

## Optional ARM64 worker

Multipass uses Apple's privileged package installer and must be bootstrapped from
an interactive terminal:

```bash
brew install --cask multipass
```

Then set the bridged interface and SSH public-key path and create the VM:

```bash
ansible-playbook ansible/playbooks/mac-worker.yml
```

Reserve the reported bridged address in DHCP and add it to local inventory as
`mac_arm_worker`. The VM has 4 CPUs, 6 GiB RAM, and a 40 GiB sparse disk by default.
It can run only images that include an ARM64 variant. It cannot access Apple Metal
or MLX and is tainted because it disappears whenever the Mac or VM is stopped.

## Build the cluster

After manually installing clean Ubuntu 26.04 on the desktop, run each stage and
review its output before continuing:

```bash
ansible-playbook ansible/playbooks/node-prepare.yml --check --diff
ansible-playbook ansible/playbooks/node-prepare.yml

ansible-playbook ansible/playbooks/control-plane.yml --check --diff
ansible-playbook ansible/playbooks/control-plane.yml

ansible-playbook ansible/playbooks/workers.yml --check --diff
ansible-playbook ansible/playbooks/workers.yml

ansible-playbook ansible/playbooks/addons.yml --check --diff
ansible-playbook ansible/playbooks/addons.yml

ansible-playbook ansible/playbooks/validate.yml
```

Fresh-host check mode can stop when a later task depends on a package repository or
file that check mode did not actually create. Apply only the reviewed preceding
stage, then rerun check mode.

The add-on stage installs pinned Cilium, MetalLB, ingress-nginx, metrics-server,
local-path storage, and NVIDIA GPU Operator releases. Local persistent volumes are
retained but remain tied to the desktop; they are not highly available.

## MLX service

Set `mlx_host_model` and `mlx_host_service_enabled: true` in local variables, then
apply `workstation.yml`. The launchd service binds to `127.0.0.1:8080` by default.
Do not bind it to the LAN until an authenticated reverse proxy and access policy are
configured.

MLX runs outside Kubernetes because it requires macOS Metal. Linux Kubernetes VMs
on the Mac can use ARM CPU and memory but do not receive Apple GPU/Metal passthrough.

## Maintenance

Upgrade or reboot only one explicitly named node at a time:

```bash
ansible-playbook ansible/playbooks/maintenance.yml \
  -e maintenance_target=ubuntu_laptop_dell_studio
```

Set `kubernetes_upgrade_minor_version`, `kubernetes_upgrade_version`, and
`kubernetes_upgrade_package_version` together for an upgrade. Set
`kubernetes_upgrade_reboot=true` only during a maintenance window. The runbook
drains, upgrades, optionally reboots, and uncordons the node.

SSH keys and host-key checking are required. Never commit private keys, Vault
password files, bootstrap tokens, or administrator kubeconfigs.
