# infrastructure

Infrastructure-as-code and cluster configuration for personal environments. The current
live cloud environment is AWS staging account `992382747916` in `us-east-1`; the layout
allows additional accounts and provider-specific GCP/Azure roots without pretending
their resources share one abstraction.

## Layout

| Path | Purpose |
|---|---|
| `deploy-units.json` | Deployable OpenTofu roots, dependencies, variables, and change detection |
| `live/aws/staging/` | State bootstrap, account baseline, and staging workloads |
| `modules/aws/` | Reusable AWS-only OpenTofu modules |
| `config/environments/` | Non-secret variables grouped by cloud and environment |
| `live/proxmox/homelab/` | Talos VM and Proxmox infrastructure managed by OpenTofu |
| `charts/` | Helm charts for cluster services and workloads |
| `ansible/` | Ubuntu worker configuration and enrollment |
| `platform/gpu-worker/` | GPU worker and inference rollout, evidence, and rollback |
| `apps/ecr/` | Container image sources; CI pushes each subdirectory to ECR |
| `apps/lambda/` | Zip Lambda sources; CI uploads arm64 packages to S3 |
| `mocks/localstack/` | Disposable local AWS sandbox |
| `live/proxmox/ubuntu-validation/` | Disposable mixed Ubuntu/Talos enrollment VM |

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

For a new account, copy the staging `live/aws` shape, create a separate environment
variable file, bootstrap that account's state backend manually, then add its roots and
dependencies to `deploy-units.json`. Use account-specific state storage and GitHub OIDC
roles. Never reuse staging state keys for another account.

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

CI plans changed deploy units using AWS GitHub OIDC. Adding the `apply` label runs the
serialized, gated apply-before-merge workflow. Bootstrap is never run in CI. Changes
under `apps/ecr/` are built and pushed to ECR by `.github/workflows/ecr-push.yml`;
update `booker_image_tag` in `config/environments/aws/staging/court-booker.tfvars` and apply to retarget the Playwright Lambda. Changes under
`apps/lambda/` are zipped by `.github/workflows/lambda-package.yml` into
`lambda-releases` (`candidate/` / `stable/`); update `booker_api_zip_key` in
`config/environments/aws/staging/court-booker-api.tfvars` to a
`stable/` key and apply to retarget the HTTP booker. Playwright EventBridge is
off; the API zip cron is the live weekly booker.

## Local systems

Talos VMs and Proxmox resources are managed with OpenTofu under
[`live/proxmox/homelab/`](live/proxmox/homelab/README.md). Cluster services and workloads
are managed with Helm charts under [`charts/`](charts/). Standalone operational and
recovery scripts remain under [`scripts/`](scripts/).

Laptop bootstrap automation is intentionally deferred. This repository does not
currently install or configure macOS packages, Homebrew bundles, or MLX services.

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

The Ubuntu/kubeadm plans are retained as historical records only. Current homelab work
uses Talos; start with [the Talos rebuild plan](docs/plans/talos-kubernetes-rebuild.md)
and the OpenTofu root documented above.
