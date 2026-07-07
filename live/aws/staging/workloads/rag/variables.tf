# --- Environment inputs (sourced from config/environments/aws/staging.tfvars) ---
variable "aws_account_id" {
  type = string
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "aws_profile" {
  type    = string
  default = "admin"
}

variable "terraform_deploy_role_name" {
  type    = string
  default = "TerraformDeploy"
}

variable "default_tags" {
  type    = map(string)
  default = {}
}

# Declared (unused here) so the environment file can be shared by staging deploy units.
variable "github_owner" {
  type    = string
  default = ""
}
variable "github_repo" {
  type    = string
  default = ""
}
variable "budget_monthly_limit_usd" {
  type    = string
  default = ""
}
variable "budget_notification_email" {
  type    = string
  default = ""
}

# GitHub repo whose Actions runs are trusted to assume the ECR-push OIDC role
# (see image_push_oidc.tf) — the workload repo that builds these images, not
# this infra repo (that trust lives in the account stack's github_owner/repo).
variable "ecr_push_github_owner" {
  type    = string
  default = ""
}
variable "ecr_push_github_repo" {
  type    = string
  default = ""
}

# --- rag-specific ---
variable "ecr_repos" {
  type        = list(string)
  default     = ["graph-rag-query", "harvest"]
  description = "ECR repos to create. Add rag-lit / repo-rag image names when needed."
}

variable "backup_noncurrent_transition_days" {
  type        = number
  default     = 30
  description = "Days before noncurrent backup versions move to cheaper storage."
}

variable "backup_run_stamped_glacier_days" {
  type        = number
  default     = 180
  description = "Days before immutable run-stamped derived-artifact tarballs (tagged lifecycle-class=run-stamped) transition to GLACIER. Transition only — never expired (dedup pointers may reference old objects)."
}
