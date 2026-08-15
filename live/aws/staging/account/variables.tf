# --- Environment inputs (config/environments/aws/staging/account.tfvars) ---
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

variable "governance_alert_email" {
  type        = string
  description = "Destination for budget reports, cost-anomaly alerts, GuardDuty, and EventBridge security mail."
}

variable "governance_contact_name" {
  type        = string
  default     = "Tushar Sariya"
  description = "Display name for account alternate contacts (billing, operations, security)."
}

variable "governance_contact_title" {
  type        = string
  default     = "Account owner"
  description = "Title for account alternate contacts."
}

variable "governance_contact_phone" {
  type        = string
  default     = ""
  description = "E.164 phone for account alternate contacts. Empty skips creating those contacts."
}

variable "homelab_ca_certificate_pem" {
  type        = string
  description = "PEM of the operator's CA certificate, registered as the Roles Anywhere trust anchor bundle. Operator-supplied via tfvars/CLI; never committed."
  default     = ""
}

variable "state_bucket_name" {
  type    = string
  default = "tofu-state-992382747916-us-east-1"
}

variable "lock_table_name" {
  type    = string
  default = "tofu-locks"
}
