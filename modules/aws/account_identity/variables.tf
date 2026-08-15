variable "aws_account_id" {
  type = string
}

variable "region" {
  type = string
}

variable "github_owner" {
  type        = string
  description = "GitHub org/user that owns the CI repo (for OIDC trust)."
}

variable "github_repo" {
  type        = string
  description = "GitHub repo name (for OIDC trust)."
}

variable "state_bucket_name" {
  type = string
}

variable "lock_table_name" {
  type = string
}

variable "homelab_ca_certificate_pem" {
  type        = string
  description = "PEM of the operator's CA certificate, registered as the Roles Anywhere trust anchor bundle. Operator-supplied via tfvars/CLI; never committed."
  # Defaults to empty so the plan-only CI job (which cannot hold a CA) still runs;
  # a real, non-empty PEM MUST be supplied at apply time for the trust anchor to work.
  default = ""
}

variable "codeartifact_domain_arn" {
  type = string
}

variable "codeartifact_domain_name" {
  type = string
}

variable "sdk_candidate_repository_arn" {
  type = string
}

variable "sdk_candidate_repository_name" {
  type = string
}

variable "sdk_stable_repository_arn" {
  type = string
}

variable "sdk_stable_repository_name" {
  type = string
}

variable "codeartifact_kms_key_arn" {
  type = string
}
