variable "region" {
  type    = string
  default = "us-east-1"
}

variable "aws_profile" {
  type    = string
  default = "admin"
}

variable "state_bucket_name" {
  type        = string
  description = "Dedicated management-account bucket for sensitive external-provider state."
}

variable "journal_table_name" {
  type    = string
  default = "external-provider-reconciliation"
}

variable "state_lock_table_name" {
  type    = string
  default = "external-provider-state-locks"
}

variable "reconciler_principal_arns" {
  type        = list(string)
  description = "Exact management-account principals allowed to assume the local reconciler role."

  validation {
    condition = (
      length(var.reconciler_principal_arns) > 0 &&
      alltrue([for arn in var.reconciler_principal_arns : can(regex("^arn:aws:iam::[0-9]{12}:(role|user)/", arn))])
    )
    error_message = "Provide at least one exact IAM role or user ARN; wildcards are not accepted."
  }
}

variable "supabase_runtime_secret_arn" {
  type        = string
  description = "Exact Secrets Manager ARN containing the Supabase PAT and database password."

  validation {
    condition     = can(regex("^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:", var.supabase_runtime_secret_arn))
    error_message = "supabase_runtime_secret_arn must be an exact Secrets Manager secret ARN."
  }
}
