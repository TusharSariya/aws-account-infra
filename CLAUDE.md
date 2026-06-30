# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

OpenTofu IaC for a single AWS account (`992382747916`, `us-east-1`). The README covers
the one-time bootstrap order and the layout table — read it for setup. This file covers
the conventions and cross-file mechanics that aren't obvious from any single file.

## Commands

```bash
# Always drive stacks through the wrapper (sets AWS_PROFILE, injects common.tfvars).
./scripts/tofu.sh <stack-dir> <subcommand> [args...]
./scripts/tofu.sh account plan
./scripts/tofu.sh stacks/rag apply

# Match CI exactly before pushing — these are the PR gate checks:
tofu fmt -check -recursive      # from repo root
tofu validate                   # from inside a stack dir, after `tofu init`
```

There is no test suite; `fmt` + `validate` + the CI `plan` are the verification loop.
`bootstrap/` uses **local state** and is run by hand once — never through CI, never via
the wrapper.

## Architecture

Three deploy units, each with its own remote-state `key` (see each `backend.tf`):
- `bootstrap/` — creates the S3 state bucket + DynamoDB lock table (local state).
- `account/` — account-wide singletons: budget alarm, GitHub OIDC provider + the two CI
  roles (`account/github_oidc.tf`).
- `stacks/rag/` — the first workload; composes the reusable modules.

`modules/encrypted_s3_bucket` and `modules/ecr_repository` are the shared building blocks.
`encrypted_s3_bucket` wraps the community KMS + s3-bucket modules and bundles versioning,
KMS encryption, public-access block, a deny-insecure-transport policy, and CloudWatch
size/object-count alarms — all toggle/threshold-driven via variables. `stacks/rag`
relaxes the inherited alarm thresholds and supplies lifecycle rules rather than
re-implementing any of that.

This repo only provisions the durable resources the **separate RAG repo** consumes (it
reads this stack's outputs). Don't add runtime/app code here.

## Dual auth: the `aws_profile` switch

Every stack's `providers.tf` keys off `var.aws_profile`:
- **Local runs** (non-empty profile, default `admin`) → the provider uses the named
  profile and an `assume_role` block targeting `TerraformDeploy`.
- **CI runs** → the workflows pass `-var "aws_profile="`, which makes the provider skip
  both the profile and the assume-role and use the OIDC role's ambient credentials
  directly (the OIDC role is already the deploy identity).

So when editing `providers.tf`, preserve the `var.aws_profile != ""` conditional on both
the `profile` arg and the dynamic `assume_role` — breaking it breaks CI or local, not both.

## CI gating model (`.github/workflows/`)

Both workflows run on `pull_request` with **no path filter** so their `*-gate` jobs are
stable required checks; a `detect` job (dorny/paths-filter) scopes the actual work to the
changed stacks (`account/**`, `modules/**`, or `common.tfvars` → account; `stacks/rag/**`
+ those shared paths → rag).

- `tofu-plan.yml` → fmt/validate/plan via the read-scoped `TOFU_PLAN_ROLE_ARN`, comments
  the plan on the PR.
- `tofu-apply.yml` → **apply-before-merge**: apply runs *on the PR* and is required, so
  main never drifts from applied infra. It only fires once the `apply` **label** is added
  (the human approval) and runs under `environment: prod` so the OIDC `sub` matches the
  apply role's trust pin. On success it enables auto-merge. There is intentionally no
  `push: main` apply.

The OIDC role ARNs are GitHub repo **variables** (`TOFU_PLAN_ROLE_ARN`,
`TOFU_APPLY_ROLE_ARN`), set from `account/` outputs after that stack is applied.

### Static scanners (credential-free required checks)

Four more workflows run on every `pull_request` and **block merge on findings**. Unlike
the tofu workflows they are pure file scans — **no OIDC, no AWS creds, no `detect`/matrix**
(so each scan job is itself the stable required-check context, named after the workflow):

- `trivy.yml` — IaC misconfig scan (`scan-type: config`, `HIGH,CRITICAL`).
- `checkov.yml` — policy-as-code (AWS ruleset, `framework: terraform`).
- `gitleaks.yml` — secret scan over full history; runs the MIT-licensed **CLI binary**, not
  `gitleaks-action` (that needs a paid license for org-owned repos like this one).
- `tflint.yml` — provider-aware lint. Runs with `TFLINT_CONFIG_FILE` set to an **absolute**
  path so `--recursive` applies the root `.tflint.hcl` (plugins + rule overrides) inside
  every stack subdir — it doesn't inherit it otherwise.

Suppressions are deliberate and justified, living in the root config files (`.tflint.hcl`,
`.trivyignore`, `.checkov.yaml`) for repo-wide conventions, or inline at the resource
(`# checkov:skip=<id>:<reason>`, `#trivy:ignore:<id> <reason>`) for one-off intentional
design (e.g. the bootstrap state bucket/lock table, the AdministratorAccess apply role,
the long-lived `rag_backup` service user). To make these truly required, add the
`trivy`/`checkov`/`gitleaks`/`tflint` checks to `main`'s branch protection.

## Conventions

- `common.tfvars` is the single source of shared inputs for all stacks; the wrapper
  injects it. Every stack re-declares all common variables — including ones it doesn't use
  — so passing the shared file never warns about undeclared vars (see the "Declared
  (unused here)" block in `stacks/rag/variables.tf`).
- `.terraform.lock.hcl` is committed on purpose (pins provider hashes); `*.tfstate` and
  `.terraform/` are gitignored.
- Provider/community-module versions are pinned (`tofu_version: 1.11.5` in CI, AWS
  provider 6.52.0). Keep them in lockstep across stacks.
- Each stack tags resources with a `stack`/`component` tag merged onto `default_tags`.
