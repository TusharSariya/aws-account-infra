variable "region" {
  type    = string
  default = "us-east-1"
}

variable "aws_profile" {
  type    = string
  default = "admin"
}

variable "management_account_id" {
  type = string
}

variable "security_account_id" {
  type        = string
  description = "Delegated security administrator account, initially Platform SharedServices."
}

variable "organization_id" {
  type = string
}

variable "cloudtrail_bucket_name" {
  type = string
}

variable "enable_guardduty" {
  type        = bool
  default     = false
  description = "Enable paid organization GuardDuty only after reviewing its projected regional cost."
}

variable "external_state_bucket_arn" {
  type        = string
  default     = ""
  description = "Optional exact sensitive external-provider state bucket ARN for CloudTrail S3 object data events."

  validation {
    condition = (
      var.external_state_bucket_arn == "" ||
      can(regex("^arn:aws:s3:::[a-z0-9][a-z0-9.-]+$", var.external_state_bucket_arn))
    )
    error_message = "external_state_bucket_arn must be empty or an exact S3 bucket ARN."
  }
}
