variable "region" {
  type = string
}

variable "account_id" {
  type = string
}

variable "environment" {
  type = string
}

variable "service_id" {
  type = string
}

variable "budget_usd" {
  type = number
}

variable "budget_emails" {
  type = list(string)
}

variable "github_owner" {
  type = string
}

variable "github_repo" {
  type = string
}

variable "state_bucket_name" {
  type = string
}

variable "apply_policy_json" {
  type        = string
  description = "Service-specific deployment policy JSON."
}
