# Repository guidance

This repository manages AWS staging infrastructure, Talos/Proxmox infrastructure,
Helm-managed cluster workloads, Ansible-managed Ubuntu workers, and a LocalStack sandbox. GCP and Azure are future
provider namespaces, not implemented environments.

## Commands

```bash
./scripts/infra.sh aws-staging-account plan
./scripts/infra.sh aws-staging-rag plan
./scripts/infra.sh aws-staging-court-booker plan
./scripts/infra.sh aws-staging-court-booker-api plan
./scripts/localstack.sh up
./scripts/localstack.sh smoke
tofu -chdir=live/proxmox/homelab plan
helm lint charts/*
./scripts/mac-operator-runner.sh status
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
  The HTTP booker is a zip Lambda under `apps/lambda/python/3.14/court-booker/` with infra in
  `live/aws/staging/workloads/lambda/python/court-booker/` (state key `stacks/court-booker-api/terraform.tfstate`).
  GitHub Actions pushes `apps/ecr/<name>` to ECR and `apps/lambda/` zips to
  `lambda-releases` (`candidate/` on PRs, `stable/` on main). It does not retarget
  Lambda until `booker_image_tag` in `config/environments/aws/staging/court-booker.tfvars`
  or `booker_api_zip_key` in `config/environments/aws/staging/court-booker-api.tfvars`
  is updated. Each deploy unit has its own var file under `config/environments/aws/staging/`.
  Playwright EventBridge is off (`schedule_enabled = false`); the API zip cron is on
  (`api_schedule_enabled = true`) once a `stable/` zip key is set. Each Lambda has its own
  SSM SecureString (`/staging/court-booker/my-y` and `/staging/court-booker-api/my-y`); they
  do not share credentials storage. Put values with `scripts/court-booker-put-secret.sh`.
  RAG and other products still keep runtime code out of this repo.

## CI invariants

- Routine CI runs on ARC through `vars.CI_EXECUTOR`.
- Cluster-mutating maintenance (admission, Proxmox/Talos plan and apply, worker,
  lifecycle, migration, capacity-host and quota jobs) runs on the macOS operator runner
  through `vars.CI_OPERATOR=mac`, using the exact expression pinned in
  `scripts/tests/test_ci_executor_routing.py`. See `docs/runbooks/mac-operator-runner.md`.
- Hosted runners are the fallback only (either variable unset). `homelab-etcd-backup` and
  `ci-runner-image/build` stay hosted by design.
- Every operator job declares `environment: prod`, which deploys from `main` only; the test
  enforces it. Required reviewers are unavailable on the current plan. The runner stays
  offline outside maintenance windows, runs as a dedicated non-admin user, and belongs in the
  repo-restricted org runner group `homelab-operator`.

## Scope boundaries

- Ubuntu worker host configuration and enrollment belong in the fresh `ansible/`
  roles. When changing GPU enrollment, inference routing, acceptance or rollback,
  follow `platform/gpu-worker/README.md`. Prove mixed-cluster enrollment in the
  disposable VM before enrolling the desktop. Ansible does not provision Talos
  control planes or deploy charts.
- Desktop power and Windows/Ubuntu boot selection remain manual. The retained-server
  power coordinator owns only its existing server queue; desktop GPU waiting must
  not wake those hosts. Inference resources reserve Kueue quota once per runtime.

- Talos VM and Proxmox infrastructure changes belong in the existing OpenTofu root;
  cluster services and workloads belong in the existing Helm charts.
- Laptop bootstrap automation is intentionally deferred. Do not add workstation,
  Homebrew, or MLX setup without a separately reviewed replacement design.
- LocalStack is for disposable experiments and smoke tests. Live roots must not be
  redirected to its endpoints.
- Cloud-specific modules are preferred over cross-cloud wrappers.

Before pushing, run relevant formatting, validation, lint, security scans, shell checks,
and LocalStack smoke tests. `.terraform.lock.hcl` files are committed deliberately;
state, retired local inventory, Vault-password files, plans, and `.terraform/` are ignored.
