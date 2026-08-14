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

variable "ecr_push_github_owner" {
  type    = string
  default = ""
}

variable "ecr_push_github_repo" {
  type    = string
  default = ""
}

variable "homelab_ca_certificate_pem" {
  type    = string
  default = ""
}

variable "booker_image_tag" {
  type        = string
  default     = ""
  description = "Immutable ECR tag (git sha). Empty skips Lambda and schedules so the first apply can create ECR."
}

variable "schedule_enabled" {
  type        = bool
  default     = false
  description = "When true, EventBridge schedules are ENABLED. Keep false until a local book succeeds."
}

variable "alert_email" {
  type        = string
  default     = "tushar.97@hotmail.com"
  description = "SES identity and destination for court-booker CloudWatch alarms. Confirm the AWS verification mail once."
}
