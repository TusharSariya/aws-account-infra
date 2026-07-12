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

The workstation role installs Homebrew tools, pyenv, tenv, SDKMAN, Helm, Helmfile,
kubectl, and Cilium CLI. MLX uses a dedicated pyenv virtual environment; Conda is
not required for MLX and remains available for projects that need it.

## Configure inventory

Copy `inventories/example` to the ignored `inventories/local` directory. Configure:

- stable addresses for every physical and virtual node;
- exactly one host in `kubernetes_control_plane`;
- workers and their capability groups;
- `kubernetes_api_endpoint`, which must remain stable;
- an unused MetalLB range outside the router's DHCP pool.

Non-secret vars live in `group_vars/all/main.yml`. The example addresses
intentionally fail preflight checks.

### Secrets (Ansible Vault)

Secrets live in `group_vars/all/vault.yml`, **encrypted** and **committed** — the
ciphertext is safe in git and makes secrets reproducible. Only the vault *password*
is out-of-band, at `~/.config/aws-account-infra/vault-password` (referenced by
`ansible.cfg`, so runs never prompt). One-time setup on a controller:

```bash
# 1. Put the shared vault password (obtained out-of-band) outside the checkout:
mkdir -p ~/.config/aws-account-infra
printf '%s' '<vault-password>' > ~/.config/aws-account-infra/vault-password
chmod 600 ~/.config/aws-account-infra/vault-password

# 2. First operator only — create the encrypted secrets from the template:
cp inventories/example/group_vars/all/vault.yml.example \
   inventories/local/group_vars/all/vault.yml
$EDITOR inventories/local/group_vars/all/vault.yml     # fill real values
make -C ansible vault-encrypt                          # encrypt in place, then commit it
```

Everyday: `make -C ansible vault-edit` / `vault-view`. Changing the vault password
(`vault-rekey`) rotates *encryption only* — it does **not** rotate the underlying
Supabase key or DSN password; do that in Supabase and re-edit the vault.

> Run playbooks via `make -C ansible <target>` (below). The Makefile exports an
> absolute `ANSIBLE_CONFIG`, so the config, inventory, and vault password resolve
> from any working directory — a bare `ansible-playbook` from the repo root does not
> pick up `ansible/ansible.cfg`. First run: `make -C ansible deps check`.

The homelab CA that signs each node's ECR client cert (`kubernetes_node`) is
referenced by `kubernetes_node_ecr_ca_{certificate,privatekey}_path`; keep those
files outside the checkout (e.g. `~/.config/aws-account-infra/homelab-ca.{crt,key}`).
Node private keys are generated **on the node** and never enter git or the vault.

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
