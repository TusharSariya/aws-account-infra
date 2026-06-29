# aws-account-infra

General-purpose OpenTofu IaC for AWS account **992382747916** (`us-east-1`), managed
from the Mac. Establishes remote state, a dedicated deploy role, an account-wide
baseline, and per-workload stacks. The first workload is the RAG backup bucket + ECR
repos (the RAG *runtime* — query server, Docker image, backup scripts — lives in the
separate RAG repo and only *consumes* this stack's outputs).

## Layout

| Path | Purpose | State |
|---|---|---|
| `bootstrap/` | Creates the S3 state bucket + DynamoDB lock table | **local** (run once) |
| `account/` | Account-wide baseline: budget alarm, account hygiene, GitHub OIDC + CI roles | remote |
| `stacks/rag/` | RAG backup S3 bucket + ECR repos | remote |
| `modules/encrypted_s3_bucket/` | Reusable: versioned + KMS + block-public S3 bucket | — |
| `modules/ecr_repository/` | Reusable: private ECR repo, scan-on-push, lifecycle | — |
| `scripts/` | One-time deploy-role bootstrap + `tofu.sh` wrapper | — |

## One-time setup (in order)

```bash
# 1. Create the Terraform deploy role (uses your `admin` profile).
AWS_PROFILE=admin ./scripts/bootstrap-terraform-deploy-role.sh

# 2. Create the remote-state backend (local state; chicken-and-egg).
cd bootstrap && AWS_PROFILE=admin tofu init && AWS_PROFILE=admin tofu apply
cd ..

# 3. Stand up the account baseline (now using remote state + assume-role).
./scripts/tofu.sh account init
./scripts/tofu.sh account apply

# 4. Stand up the first workload.
./scripts/tofu.sh stacks/rag init
./scripts/tofu.sh stacks/rag apply
```

`scripts/tofu.sh <stack-dir> <tofu-args...>` wraps `tofu` with `AWS_PROFILE` and the
shared `common.tfvars` so every stack is invoked consistently.

## State backend

S3 bucket `tofu-state-992382747916-us-east-1` + DynamoDB lock table `tofu-locks`
(created by `bootstrap/`). Each stack uses a distinct `key` (see its `backend.tf`).

## CI/CD

GitHub Actions authenticate via **OIDC** (no stored AWS keys) to roles created in
`account/github_oidc.tf`:
- **PR** → `tofu-plan.yml`: `fmt -check`, `validate`, `plan` (commented), via the
  read-scoped plan role.
- **merge to `main`** → `tofu-apply.yml`: `apply`, gated by the `prod` GitHub
  Environment (required reviewer), via the apply role.
`bootstrap/` is never run in CI.

## Before the first apply — confirm these

- `common.tfvars`: `github_owner`/`github_repo`, `budget_*` values (marked `TODO`).
- The `prod` GitHub Environment + a required reviewer (configured in GitHub settings).
