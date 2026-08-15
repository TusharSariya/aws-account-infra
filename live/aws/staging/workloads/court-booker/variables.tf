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

variable "booker_image_tag" {
  type        = string
  default     = ""
  description = "Immutable ECR tag (git sha). Empty skips Lambda and schedules so the first apply can create ECR."
}

variable "schedule_enabled" {
  type        = bool
  default     = false
  description = "When true, Playwright EventBridge schedules are ENABLED. Parked false while the API zip booker is the live cron."
}

variable "alert_email" {
  type        = string
  default     = "tushar.97@hotmail.com"
  description = "SES identity and destination for court-booker CloudWatch alarms. Confirm the AWS verification mail once."
}
