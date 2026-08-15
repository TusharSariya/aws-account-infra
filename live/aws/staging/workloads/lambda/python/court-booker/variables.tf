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

# Declared because this unit shares config/environments/aws/staging.tfvars
# with the Playwright court-booker stack. Do not use them here.
variable "booker_image_tag" {
  type    = string
  default = ""
}

variable "schedule_enabled" {
  type    = bool
  default = false
}

variable "booker_api_zip_key" {
  type        = string
  default     = ""
  description = "S3 object key for the zip (git sha). Empty skips Lambda and schedules so the first apply can create the bucket."
}

variable "api_schedule_enabled" {
  type        = bool
  default     = false
  description = "When true, EventBridge schedules for the API booker are ENABLED. Playwright stays on schedule_enabled (currently parked false)."
}

variable "alert_email" {
  type        = string
  default     = "tushar.97@hotmail.com"
  description = "SES destination for court-booker-api CloudWatch alarms. Reuses the identity created by the Playwright stack."
}
