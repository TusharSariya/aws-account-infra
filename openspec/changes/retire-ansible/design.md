## Context

See `proposal.md` for motivation. The tracked `ansible/` tree spans host configuration, Kubernetes bootstrap, laptop setup, Homebrew, MLX, inventories, and encrypted Vault data. The current repository also has Talos/OpenTofu/Helm management, independent operational scripts, and a combined workflow whose shell job is still required. The removal must preserve private recoverability without decrypting secrets and must not modify live systems.

## Goals / Non-Goals

**Goals:**

- Make Ansible retirement atomic and auditable in one repository change.
- Preserve the shell-validation contract while removing Ansible dependencies.
- Keep historical design context readable without making it look operational.
- Demonstrate that deployment selection remains unchanged.

**Non-Goals:**

- Replacing laptop bootstrap or MLX automation.
- Changing host configuration, running services, infrastructure state, credentials, required checks, or Git history.
- Retiring independent server and recovery scripts.

## Decisions

### Preserve ciphertext outside the checkout before deletion

Copy only the committed encrypted Vault file to `~/.config/aws-account-infra/retired-ansible/<timestamp>/vault.yml`, set restrictive modes, and compare SHA-256 digests. This keeps a recoverable copy without accessing plaintext or altering the existing password. Keeping another tracked copy was rejected because it would fail the complete-removal boundary.

### Convert the workflow in place

Rename `ansible.yml` to `shell.yml` and retain only the existing `shell` job. This preserves job behavior and runner selection while removing Ansible installation, collection, lint, syntax, and placeholder-password steps. Creating an unrelated workflow was rejected because the existing workflow is already a shared shell validation boundary.

### Remove the Ansible detector scope

Delete the Ansible patterns and map the shell scope directly to `shell.yml`. Focused tests cover scripts, tests, the workflow, shared CI dependencies, deleted matching paths, and documentation-only changes. Compatibility aliases were rejected because they would keep a retired concept active.

### Separate current guidance from historical records

Rewrite current README and repository guidance around Talos/OpenTofu/Helm. Retained Ubuntu/kubeadm-era documents receive a prominent historical notice and use pre-removal GitHub blob URLs for removed sources. Deleting all historical design documents was rejected because they retain architectural context; leaving live-looking commands or broken relative links was rejected as unsafe.

## Risks / Trade-offs

- [Historical documents may still be mistaken for current operations] -> Add a prominent non-executable banner and pin removed source links to the pre-removal commit.
- [Broad deletion could remove independent interfaces] -> Limit deletion to tracked `ansible/`, the obsolete Vault runbook, and Ansible-only CI while inventorying standalone scripts and tests before and after.
- [The renamed workflow could stop running when relevant files are deleted] -> Keep full-diff, no-renames detection and add focused tests using old and new matching paths.
- [A private archive could have permissive permissions or altered bytes] -> Set explicit modes and verify both SHA-256 digests before repository deletion.

## Migration Plan

1. Create an isolated worktree from current `origin/main`.
2. Preserve and verify the Vault ciphertext privately.
3. Delete the tracked Ansible tree and obsolete runbook; simplify ignore rules.
4. Rename and reduce CI to shell validation; update detector logic and tests.
5. Rewrite current guidance and mark retained legacy documents historical with pinned source links.
6. Run focused and repository validation, including deployment selection, strict OpenSpec validation, link checks, and secret scanning.
7. Commit and open a removal pull request. Rollback is a normal revert; the ciphertext remains available in Git history and the private archive.
