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

variable "provision_oauth" {
  description = "Prepare empty credential stores; enable only for the staged API migration."
  type        = bool
  default     = false
}

variable "auth_maintenance_enabled" {
  description = "Enable hourly token maintenance after successful local bootstrap."
  type        = bool
  default     = false
}
