# Ubuntu worker configuration

These fresh roles adopt an existing Ubuntu 26.04 installation. They own host
identity, Wi-Fi, SSH access, optional bootstrapped Tailscale, suspend prevention,
packages, containerd, the local API proxy, cached assets, and kubelet enrollment.
OpenTofu owns the disposable validation VM. Helm/OpenTofu owns cluster resources.

Installation, disk selection, Secure Boot enrollment when required, initial SSH,
Tailscale login, and interactive sudo are bootstrap prerequisites. Secrets stay
outside Git. No role changes Windows, partitions, EFI boot order, or desktop power.

Use the [ordered rollout](../platform/gpu-worker/README.md). Enrollment defaults
to disabled. The existing SSH alias is stale; inventory uses `10.0.0.226` directly.

```
export ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg"
ansible-galaxy collection install -r ansible/requirements.yml
ansible-playbook -i ansible/inventories/example/gpu.yml ansible/playbooks/worker-health.yml
ansible-playbook -i /PRIVATE/inventory.yml ansible/playbooks/ubuntu-worker.yml \
  -e @/PRIVATE/worker-vars.json --ask-become-pass --check --diff
ansible-playbook -i /PRIVATE/inventory.yml ansible/playbooks/ubuntu-worker.yml \
  -e @/PRIVATE/worker-vars.json --ask-become-pass
```

Repeat apply and require no unexpected changes. Check mode cannot establish
convergence on a fresh host when earlier tasks only predict files/packages.
Wi-Fi credential changes are suppressed from output and diff. Leave
`worker_host_wifi_psk` empty to retain existing system-owned credentials. The
current desktop connection is already available to all users, autoconnects, and
stores its credential with NetworkManager (`psk-flags=0`). A newly installed host
must provide a private PSK and system-wide connection during bootstrap.

The package pins were queried from the desktop's Ubuntu repositories and upstream
Kubernetes/NVIDIA repositories. Package availability does not prove runtime
compatibility. Do not mark hardware acceptance complete based on lint or syntax.
