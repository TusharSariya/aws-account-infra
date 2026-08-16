variable "region" {
  type = string
}

variable "aws_profile" {
  type    = string
  default = "admin"
}

variable "account_ids" {
  type        = set(string)
  description = "All vended account IDs receiving emergency admin and read-only access."
}

variable "operator_account_ids" {
  type        = set(string)
  description = "Workload accounts receiving the operator permission set."
}

variable "platform_admin_group_name" {
  type    = string
  default = "PlatformAdmins"
}

variable "workload_operator_group_name" {
  type    = string
  default = "WorkloadOperators"
}

variable "readonly_group_name" {
  type    = string
  default = "AWSReadOnly"
}
