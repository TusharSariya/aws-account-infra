# Plan: Ansible Vault for the homelab

Encrypt-at-rest secret handling for the Ansible layer, introduced with the KEDA
harvester deploy (Supabase `service_role` key, KEDA scaler DSN). Reviewed by a
GPT-5.6 consult (2026-07-12); its corrections are folded in below.

## Decisions (all three "proper" options chosen)
1. **Commit the ciphertext.** The encrypted `group_vars/all/vault.yml` is tracked in
   git; only the vault *password* is out-of-band. Survives `git clean -x` / laptop
   loss and lets a fresh operator reproduce secrets from just the password.
2. **On-node CSR for node identity.** Each node generates its own private key and a
   CSR; the controller signs the CSR with the homelab CA and returns only the public
   cert. The private key never leaves the node, never enters git or the vault.
3. **`ANSIBLE_CONFIG` via `make`.** `ansible/Makefile` exports an absolute
   `ANSIBLE_CONFIG` so config/inventory/vault-password resolve from any cwd.

## Layout
```
~/.config/aws-account-infra/vault-password        # NEVER committed; referenced by ansible.cfg
~/.config/aws-account-infra/homelab-ca.{crt,key}  # CA, outside the checkout
ansible/ansible.cfg                               # vault_password_file = ~/.config/.../vault-password
ansible/Makefile                                  # exports ANSIBLE_CONFIG; deploy + vault targets
ansible/inventories/example/group_vars/all/
    main.yml            # non-secret vars (committed)
    vault.yml.example   # secrets TEMPLATE (committed plaintext; ansible ignores .example)
ansible/inventories/local/group_vars/all/
    main.yml            # real non-secret vars (gitignored)
    vault.yml           # real secrets, ENCRYPTED (committed via .gitignore negation)
```

## Key facts confirmed by the consult
- A relative `vault_password_file` in `ansible.cfg` resolves against the **cfg dir**,
  not cwd. We sidestep it entirely with a `~`-absolute path.
- `group_vars/all/` (dir) **silently wins** over `group_vars/all.yml` (file) — the old
  file must be removed in the same change (done).
- Files under `group_vars/all/` load lexically (`main.yml` then `vault.yml`); keys are
  kept disjoint.
- `.gitignore` cannot re-include a file whose parent dir is ignored, so the exception
  re-includes each parent dir on the way down to `vault.yml`.

## Security posture
- Only true secrets are encrypted (service key, DSN). Supabase URL + public CA cert
  are plaintext.
- Secret-consuming tasks use `no_log: true`; the harvester asserts fail early on
  missing/placeholder secrets rather than silently skipping.
- DSN password must be percent-encoded; `sslmode=require` is explicit.
- `.gitignore` is a guardrail, not a boundary: `*.key`, `homelab-ca.*`, `*.srl`
  ignored; vault password file `chmod 600`.

## Follow-ups (not in this change)
- `kubectl create secret --from-literal=` still passes the secret on argv (visible to
  local `ps` during the run). Low risk on a single-user controller; harden later by
  templating the Secret manifest (base64 `data:`) instead of `--from-literal`.
- `--check --diff` can render secrets; audited tasks are `no_log`, but keep this in
  mind when adding new ones.
