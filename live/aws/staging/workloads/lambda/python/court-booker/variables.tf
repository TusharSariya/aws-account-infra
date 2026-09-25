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

variable "ack_mode" {
  type        = string
  default     = "off"
  description = "Friend ACK window after a booking: off (no ack resources), notify_only (email only, never cancels), enforce (cancel the held reservation when quorum is not reached)."

  validation {
    condition     = contains(["off", "notify_only", "enforce"], var.ack_mode)
    error_message = "ack_mode must be one of off, notify_only, enforce."
  }
}

variable "ack_required" {
  type        = number
  default     = 1
  description = "Number of friend accepts that confirm a booked court."

  validation {
    condition     = var.ack_required >= 1 && floor(var.ack_required) == var.ack_required
    error_message = "ack_required must be a whole number of at least 1."
  }
}

variable "ack_window_hours" {
  type        = number
  default     = 24
  description = "Hours friends have to accept after booking. The deadline is also capped at 6 hours before the slot."

  validation {
    condition     = var.ack_window_hours >= 1 && var.ack_window_hours <= 72
    error_message = "ack_window_hours must be between 1 and 72 (the ack state machine times out after 72 hours)."
  }
}

variable "ack_sender_email" {
  type        = string
  default     = null
  nullable    = true
  description = "Verified SES identity that sends ACK invites. null falls back to alert_email."
}
