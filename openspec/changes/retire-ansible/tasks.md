## 1. Preserve and Remove Ansible

- [x] 1.1 Preserve the committed Vault ciphertext in a timestamped private directory with `0700`/`0600` modes and verify matching SHA-256 digests without decrypting it
- [x] 1.2 Delete the tracked `ansible/` tree and obsolete Vault runbook, simplify `.gitignore` while retaining private inventory and Vault-password protections, and verify no tracked Ansible implementation remains

## 2. Preserve Shell Validation

- [x] 2.1 Replace `ansible.yml` with `shell.yml`, retaining the shell job, ShellCheck/Bats coverage, fork restrictions, and runner selection while verifying no Ansible steps or placeholder secret remain
- [x] 2.2 Remove the Ansible change-detection scope, map shell inputs to `shell.yml`, and verify focused tests cover shell scripts, shell tests, workflow/shared inputs, deleted paths, and documentation-only changes

## 3. Update Guidance

- [x] 3.1 Update the main README and repository guidance for Talos/OpenTofu/Helm management and deferred laptop bootstrap, verifying no current Ansible commands remain
- [x] 3.2 Mark retained Ubuntu/kubeadm-era documentation historical and pin removed source links to the pre-removal revision, verifying Markdown links do not target deleted paths
- [x] 3.3 Verify standalone server and recovery scripts and tests remain tracked and unchanged in scope

## 4. Validate and Deliver

- [x] 4.1 Run ShellCheck, Bats, focused Python tests, workflow validation, Markdown-link checks, secret scanning, and strict OpenSpec validation, recording any unavailable check explicitly
- [x] 4.2 Verify the deployment selector requests no infrastructure changes and active repository references do not depend on deleted Ansible files
- [x] 4.3 Commit the bounded removal branch and open a pull request with the current required checks unchanged, verifying the PR reports passing shell validation
