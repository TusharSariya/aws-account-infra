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

variable "booker_api_zip_key" {
  type        = string
  default     = ""
  description = "S3 object key under lambda-releases, e.g. stable/court-booker/<sha>.zip. Empty or non-stable skips Lambda and schedules."
}

variable "api_schedule_enabled" {
  type        = bool
  default     = false
  description = "When true, EventBridge schedules for the API booker are ENABLED."
}

variable "alert_email" {
  type        = string
  default     = "tushar.97@hotmail.com"
  description = "SES destination for court-booker-api CloudWatch alarms. Reuses the identity created by the Playwright stack."
}
