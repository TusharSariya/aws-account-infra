# Repository guidance

This repository manages AWS staging infrastructure, local host configuration, and a
LocalStack sandbox. Kubernetes is documentation-only. GCP and Azure are future provider
namespaces, not implemented environments.

## Commands

```bash
./scripts/infra.sh aws-staging-account plan
./scripts/infra.sh aws-staging-rag plan
./scripts/infra.sh aws-staging-court-booker plan
./scripts/localstack.sh up
./scripts/localstack.sh smoke
ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook ansible/playbooks/workstation.yml --check --diff
ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook ansible/playbooks/compute.yml --check --diff
```

OpenTofu roots and dependencies are declared in `deploy-units.json`. Update the manifest
when adding or relocating a root; CI derives its matrix from that file. Environment
variables live under `config/environments`, and secrets must not be committed.

## AWS invariants

- Preserve existing staging backend keys unless performing an explicit, backed-up state
  migration.
- Local AWS providers use `aws_profile` and assume `TerraformDeploy`; CI overrides
  `aws_profile` with an empty value and uses its ambient OIDC role.
- Bootstrap uses local state and is always manual.
- Provider and community-module versions remain pinned across roots.
- Account-level dependencies precede workload roots in `deploy-units.json`.
- Application runtime code belongs in its workload repository, not here.
  Exception: `apps/ecr/court-booker/` is a small Playwright Lambda image whose infra lives in
  `live/aws/staging/workloads/court-booker/` (own state key `stacks/court-booker/terraform.tfstate`).
  GitHub Actions pushes `apps/ecr/<name>` to ECR; it does not retarget Lambda until
  `booker_image_tag` in `config/environments/aws/staging.tfvars` is updated.
  RAG and other products still keep runtime code out of this repo.

## Scope boundaries

- Ansible can manage the Mac workstation and Ubuntu compute baseline. It must not install
  Kubernetes until `docs/plans/kubernetes.md` has been separately reviewed and approved.
- LocalStack is for disposable experiments and smoke tests. Live roots must not be
  redirected to its endpoints.
- Cloud-specific modules are preferred over cross-cloud wrappers.

Before pushing, run relevant formatting, validation, lint, security scans, Ansible syntax
checks, and LocalStack smoke tests. `.terraform.lock.hcl` files are committed deliberately;
state, local inventory, Vault password files, plans, and `.terraform/` are ignored.
