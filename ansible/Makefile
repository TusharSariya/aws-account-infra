# Ansible entrypoint. Its only job beyond convenience is to export ANSIBLE_CONFIG as
# an ABSOLUTE path, so ansible discovers ansible.cfg (and therefore the inventory,
# roles_path, and vault_password_file) no matter which directory you invoke it from.
# Without this, running from the repo root silently ignores ansible/ansible.cfg.
#
# Run from anywhere:  make -C ansible harvester
#                     make -C ansible check          # verify config + inventory resolve
#                     make -C ansible vault-edit      # edit the encrypted secrets
export ANSIBLE_CONFIG := $(CURDIR)/ansible.cfg

VAULT := inventories/local/group_vars/all/vault.yml
CHECK ?=            # set CHECK=1 for a dry run: make -C ansible harvester CHECK=1
_CHECK := $(if $(CHECK),--check --diff,)

.PHONY: deps check syntax-check compute node-prepare addons harvester validate \
        vault-edit vault-view vault-create vault-encrypt vault-rekey

deps:  ## Install pinned collections
	ansible-galaxy collection install -r requirements.yml

## --- Bootstrap verification (run after configuring inventory + vault) ---
check:  ## Show the resolved config + inventory graph (confirms ANSIBLE_CONFIG took effect)
	ansible-config dump --only-changed
	ansible-inventory --graph

syntax-check:  ## Parse every playbook without contacting hosts
	ansible-playbook playbooks/site.yml --syntax-check

## --- Deploy (append CHECK=1 for --check --diff) ---
compute:;      ansible-playbook playbooks/compute.yml --limit ubuntu_desktop $(_CHECK)
node-prepare:; ansible-playbook playbooks/node-prepare.yml $(_CHECK)
addons:;       ansible-playbook playbooks/addons.yml $(_CHECK)
harvester:;    ansible-playbook playbooks/harvester.yml $(_CHECK)
validate:;     ansible-playbook playbooks/validate.yml

## --- Vault (password comes from vault_password_file in ansible.cfg) ---
vault-create:  ## Create the encrypted secrets file from scratch
	ansible-vault create $(VAULT)
vault-encrypt: ## Encrypt a plaintext $(VAULT) in place (after copying from vault.yml.example)
	ansible-vault encrypt $(VAULT)
vault-edit:    ## Edit the encrypted secrets
	ansible-vault edit $(VAULT)
vault-view:    ## Print the decrypted secrets to stdout
	ansible-vault view $(VAULT)
vault-rekey:   ## Change the vault password (needs a NEW password file; see README)
	@echo "Rekey rotates ENCRYPTION only, not the underlying credentials. See ansible/README.md."
	ansible-vault rekey $(VAULT)
