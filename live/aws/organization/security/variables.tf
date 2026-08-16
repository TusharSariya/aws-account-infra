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
