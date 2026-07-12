# Shared inputs for AWS staging deploy units. The infra wrapper selects this file from
# deploy-units.json. Adjust the placeholders marked TODO before the first apply.

aws_account_id = "992382747916"
region         = "us-east-1"

# Source profile that holds credentials allowed to assume the deploy role.
# Created/owned outside this repo (your ~/.aws/config). See scripts/bootstrap-terraform-deploy-role.sh.
aws_profile = "admin"

# Dedicated execution role assumed by every stack (created by the bootstrap-role script).
terraform_deploy_role_name = "TerraformDeploy"

# GitHub repo that CI runs from — used to pin the OIDC role trust policy.
# TODO: confirm this matches the remote you create for this repo.
github_owner = "TusharSariyaOrg"
github_repo  = "aws-account-infra"

# Workload repo trusted to assume the rag stack's ECR-push OIDC role (builds
# and pushes the harvest / graph-rag-query images). Different repo from this
# infra repo's own CI identity above.
ecr_push_github_owner = "TusharSariyaOrg"
ecr_push_github_repo  = "excalidraw-tf-rag"

# Account-wide default tags merged onto every resource.
default_tags = {
  managed_by = "opentofu"
  repo       = "aws-account-infra"
}

# AWS Budgets monthly cost alarm (account/ stack).
# TODO: set a real notification email and your tolerance.
budget_monthly_limit_usd  = "20"
budget_notification_email = "tushar.sariya77@gmail.com"

# --- Homelab ECR-pull identity (IAM Roles Anywhere) -----------------------------
# The operator's own CA certificate (PEM), registered as the trust anchor that
# validates each node's client cert. This is a PUBLIC cert, not a secret, but it is
# environment-specific — BRING YOUR OWN CA and supply it here or via `-var`/`-var-file`
# at apply time. Left unset on purpose so a real CA is never committed. Example:
# homelab_ca_certificate_pem = <<-EOT
#   -----BEGIN CERTIFICATE-----
#   ...your homelab CA cert...
#   -----END CERTIFICATE-----
# EOT
