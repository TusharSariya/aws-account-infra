variable "bucket_name" {
  type = string
}

variable "kms_description" {
  type    = string
  default = "KMS key for S3 bucket encryption"
}

variable "kms_deletion_window_in_days" {
  type    = number
  default = 7
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "lifecycle_rules" {
  type        = any
  default     = []
  description = "Passed through to terraform-aws-modules/s3-bucket `lifecycle_rule`. Empty disables lifecycle."
}

variable "create_bucket_size_alarm" {
  type    = bool
  default = true
}

variable "bucket_size_alarm_name" {
  type    = string
  default = null
}

variable "bucket_size_bytes_threshold" {
  type        = number
  default     = 1099511627776
  description = "Default 1 TiB — tune per environment."
}

variable "bucket_size_alarm_period_seconds" {
  type    = number
  default = 86400
}

variable "create_object_count_alarm" {
  type    = bool
  default = true
}

variable "object_count_alarm_name" {
  type    = string
  default = null
}

variable "object_count_threshold" {
  type        = number
  default     = 1000000
  description = "Alarm when StandardStorage object count exceeds this value."
}

variable "object_count_alarm_period_seconds" {
  type    = number
  default = 86400
}

variable "attach_deny_insecure_transport_policy" {
  type        = bool
  default     = true
  description = "Deny all S3 actions when aws:SecureTransport is false."
}

variable "object_lock_retention_days" {
  description = "Optional governance retention; null preserves existing buckets without Object Lock. Enabling Object Lock cannot be undone."
  type        = number
  default     = null
  validation {
    condition     = var.object_lock_retention_days == null ? true : (var.object_lock_retention_days >= 1 && var.object_lock_retention_days == floor(var.object_lock_retention_days))
    error_message = "Retention must be null or a positive whole number of days."
  }
}

variable "protect_bucket_deletion" {
  type        = bool
  default     = false
  description = "Explicitly deny DeleteBucket. Removing this protection requires a reviewed policy change."
}

variable "use_s3_managed_encryption" {
  description = "Use SSE-S3 for new objects. Retain the existing KMS key for historical versions and other consumers until a separate verified retirement."
  type        = bool
  default     = false
}
