variable "aws_account_id" {
  type = string
}

variable "region" {
  type = string
}

variable "budget_monthly_limit_usd" {
  type        = string
  description = "Monthly cost budget threshold in USD."
}

variable "budget_notification_email" {
  type        = string
  description = "Email notified when the budget alarm trips."
}

variable "governance_alert_email" {
  type        = string
  description = "Destination for budget reports, cost-anomaly alerts, GuardDuty, and EventBridge security mail."
}

variable "governance_contact_name" {
  type        = string
  default     = "Tushar Sariya"
  description = "Display name for account alternate contacts (billing, operations, security)."
}

variable "governance_contact_title" {
  type        = string
  default     = "Account owner"
  description = "Title for account alternate contacts."
}

variable "governance_contact_phone" {
  type        = string
  default     = ""
  description = "E.164 phone for account alternate contacts. Empty skips creating those contacts."
}
