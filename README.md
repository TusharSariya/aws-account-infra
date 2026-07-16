# infrastructure

Infrastructure-as-code and host configuration for personal environments. The current
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
| `ansible/` | macOS administration workstation and Ubuntu compute configuration |
| `mocks/localstack/` | Disposable local AWS sandbox |
| `docs/plans/kubernetes.md` | Review-only Kubernetes proposal; nothing implements it yet |

## AWS staging

The existing remote state coordinates and keys are unchanged:

- Bucket: `tofu-state-992382747916-us-east-1`
- Lock table: `tofu-locks`
- Keys: `account/terraform.tfstate` and `stacks/rag/terraform.tfstate`

For an existing checkout, reattach each relocated root before making changes:

```bash
./scripts/infra.sh aws-staging-account init -reconfigure
./scripts/infra.sh aws-staging-account plan
./scripts/infra.sh aws-staging-rag init -reconfigure
./scripts/infra.sh aws-staging-rag plan
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
```

CI plans changed deploy units using AWS GitHub OIDC. Adding the `apply` label runs the
serialized, gated apply-before-merge workflow. Bootstrap is never run in CI.

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

Kubernetes remains intentionally deferred. Review and complete every open prerequisite
in [docs/plans/kubernetes.md](docs/plans/kubernetes.md) before adding automation.
