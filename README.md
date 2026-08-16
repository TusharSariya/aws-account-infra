# infrastructure

Infrastructure-as-code and host configuration for personal environments. The current
live cloud environment is AWS staging account `992382747916` in `us-east-1`; the layout
allows additional accounts and provider-specific GCP/Azure roots without pretending
their resources share one abstraction.

## Layout

| Path | Purpose |
|---|---|
| `deploy-units.json` | Deployable OpenTofu roots, dependencies, variables, and change detection |
| `catalog/` | Immutable service, repository, OU, account, budget, and deployment declarations |
| `live/aws/organization/` | Recoverable organization, account, bootstrap, access, and GitHub repository roots |
| `live/aws/staging/` | State bootstrap, account baseline, and staging workloads |
| `modules/aws/` | Reusable AWS-only OpenTofu modules |
| `config/environments/` | Non-secret variables grouped by cloud and environment |
| `ansible/` | macOS administration workstation and Ubuntu compute configuration |
| `apps/ecr/` | Container image sources; CI pushes each subdirectory to ECR |
| `apps/lambda/` | Zip Lambda sources; CI uploads arm64 packages to S3 |
| `mocks/localstack/` | Disposable local AWS sandbox |
| `docs/kubernetes-vending.md` | Kubernetes 1.35 rebuild, vending controls, rollout gates, and recovery runbook |

## AWS staging

The existing remote state bucket and lock table are unchanged. Keys:

- `account/terraform.tfstate` — account baseline
- `stacks/rag/terraform.tfstate` — RAG
- `stacks/court-booker/terraform.tfstate` — court booker Playwright container
- `stacks/court-booker-api/terraform.tfstate` — court booker HTTP zip Lambda

For an existing checkout, reattach each relocated root before making changes:

```bash
./scripts/infra.sh aws-staging-account init -reconfigure
./scripts/infra.sh aws-staging-account plan
./scripts/infra.sh aws-staging-rag init -reconfigure
./scripts/infra.sh aws-staging-rag plan
./scripts/infra.sh aws-staging-court-booker init
./scripts/infra.sh aws-staging-court-booker plan
./scripts/infra.sh aws-staging-court-booker-api init
./scripts/infra.sh aws-staging-court-booker-api plan
```

Both migration plans must show no resource changes. Do not apply a migration plan that
proposes replacement or deletion.

New accounts are declared under `catalog/services/` and created one at a time through the
protected `account-vend` workflow. Each account gets its own state bucket, budget, cost
anomaly alert, deployment artifact bucket, and repository-scoped GitHub OIDC roles. See
[docs/account-vending.md](docs/account-vending.md) for initialization and recovery.

### Initial staging bootstrap

```bash
AWS_PROFILE=admin ./scripts/bootstrap-terraform-deploy-role.sh
cd live/aws/staging/bootstrap
AWS_PROFILE=admin tofu init
AWS_PROFILE=admin tofu apply
cd ../../../..
./scripts/infra.sh aws-staging-account init
./scripts/infra.sh aws-staging-account apply
./scripts/infra.sh aws-staging-rag init
./scripts/infra.sh aws-staging-rag apply
./scripts/infra.sh aws-staging-court-booker init
./scripts/infra.sh aws-staging-court-booker apply
./scripts/infra.sh aws-staging-court-booker-api init
./scripts/infra.sh aws-staging-court-booker-api apply
```

Pull requests run formatting and provider validation without AWS credentials. After merge,
the serialized `tofu-apply` workflow runs through the protected `platform-prod` environment;
that environment must require approval and restrict deployments to `main`. Changes
under `apps/ecr/` are built and pushed to ECR by `.github/workflows/ecr-push.yml`;
update `booker_image_tag` in `config/environments/aws/staging/court-booker.tfvars` and apply to retarget the Playwright Lambda. Changes under
`apps/lambda/` are tested and zipped without AWS credentials on pull requests. The
main-branch job assumes the stable publisher role and uploads to `lambda-releases/stable/`;
update `booker_api_zip_key` in
`config/environments/aws/staging/court-booker-api.tfvars` to a
`stable/` key and apply to retarget the HTTP booker. Playwright EventBridge is
off; the API zip cron is the live weekly booker.

## Local systems

See [ansible/README.md](ansible/README.md) for inventory and host configuration. Actual
inventory is gitignored; the committed inventory contains documentation addresses only.

LocalStack is a sandbox, not a live-stack test backend:

```bash
./scripts/localstack.sh up
./scripts/localstack.sh smoke
./scripts/localstack.sh down
```

## Pre-push checks

Pushes are gated by the same static scanners CI runs (checkov, `terraform fmt`,
etc.). Pick **one** local gate and install it once per clone:

- Native scanner script (Docker-based; also runs trivy, gitleaks, tflint):

  ```bash
  ./scripts/install-hooks.sh   # sets core.hooksPath -> scripts/git-hooks
  ```

- Or the [pre-commit](https://pre-commit.com) framework (`.pre-commit-config.yaml`;
  checkov pinned to the CI image `3.3.8`, plus `terraform_fmt` / `terraform_validate`):

  ```bash
  git config --unset-all core.hooksPath   # pre-commit refuses while this is set
  pre-commit install --hook-type pre-push
  ```

Both block the push on any finding; bypass a single push with `git push --no-verify`.

## Future providers

Add provider-native roots as `live/gcp/<environment>/...` or
`live/azure/<environment>/...`, provider-native modules under `modules/<cloud>/`, and
cloud-specific variables under `config/environments/<cloud>/`. Extend CI authentication
for that provider before setting a unit's `ci` field to true. Do not place credentials in
variable files or create generic modules whose inputs merely mirror provider resources.

Kubernetes service vending is implemented as gated IaC. Ansible owns cluster and tenant
controls, Helmfile owns pinned add-ons, and Argo owns only the explicit application-kind
allowlist. All enablement flags remain false until the evidence in
[docs/kubernetes-vending.md](docs/kubernetes-vending.md) is recorded.
