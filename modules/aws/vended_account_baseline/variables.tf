variable "account_id" {
  type = string
}

variable "region" {
  type = string
}

variable "service_id" {
  type = string
}

variable "environment" {
  type = string
}

variable "budget_usd" {
  type = number
}

variable "budget_emails" {
  type = list(string)

  validation {
    condition     = length(var.budget_emails) > 0
    error_message = "At least one confirmed budget recipient is required."
  }
}

variable "cost_anomaly_threshold_usd" {
  type        = number
  default     = 5
  description = "Minimum absolute impact in USD before sending a cost anomaly alert."

  validation {
    condition     = var.cost_anomaly_threshold_usd > 0
    error_message = "The anomaly threshold must be positive."
  }
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
  description = "Service-specific deployment permissions. Generic AdministratorAccess is intentionally unsupported."
}
