# --- Environment inputs (sourced from config/environments/aws/staging.tfvars) ---
variable "aws_account_id" {
  type = string
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "aws_profile" {
  type        = string
  default     = "admin"
  description = "Source profile that can assume the deploy role."
}

variable "terraform_deploy_role_name" {
  type    = string
  default = "TerraformDeploy"
}

variable "default_tags" {
  type    = map(string)
  default = {}
}

variable "github_owner" {
  type        = string
  description = "GitHub org/user that owns the CI repo (for OIDC trust)."
}

variable "github_repo" {
  type        = string
  description = "GitHub repo name (for OIDC trust)."
}

# --- account-specific ---
variable "budget_monthly_limit_usd" {
  type        = string
  description = "Monthly cost budget threshold in USD."
  default     = "20"
}

variable "budget_notification_email" {
  type        = string
  description = "Email notified when the budget alarm trips."
}

variable "state_bucket_name" {
  type    = string
  default = "tofu-state-992382747916-us-east-1"
}

variable "lock_table_name" {
  type    = string
  default = "tofu-locks"
}
