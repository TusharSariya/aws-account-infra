# Local compute configuration

Ansible configures this Mac as the administration workstation and the physical Ubuntu
computers as general-purpose compute. It intentionally does not install Kubernetes.

## Bootstrap

1. Install Homebrew and run `brew install ansible` on the Mac.
2. Run `ansible-galaxy collection install -r ansible/requirements.yml`.
3. Copy `ansible/inventories/example` to `ansible/inventories/local` and replace the
   documentation addresses and SSH users.
4. Confirm SSH host keys manually with `ssh <host>` before running Ansible.
5. Store secrets in a Vault-encrypted local variables file, for example:
   `ansible-vault create ansible/inventories/local/group_vars/vault.yml`.

From the repository root:

```bash
ansible-playbook ansible/playbooks/workstation.yml
ansible-playbook ansible/playbooks/compute.yml --check --diff
ansible-playbook ansible/playbooks/compute.yml
```

The Ubuntu playbook uses privilege escalation and prompts for the sudo password. SSH
keys are preferred; never commit private keys or a Vault password file.
