# --- Common inputs (sourced from ../../common.tfvars) ---
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

# Declared (unused here) so common.tfvars keys don't warn as undeclared.
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

# --- rag-specific ---
variable "ecr_repos" {
  type        = list(string)
  default     = ["graph-rag-query"]
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
