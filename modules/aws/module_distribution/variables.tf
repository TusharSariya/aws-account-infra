variable "bucket_name" {
  type = string
}

variable "organization_id" {
  type = string
}

variable "github_oidc_provider_arn" {
  type = string
}

variable "github_owner" {
  type = string
}

variable "github_repo" {
  type = string
}

variable "retention_days" {
  type    = number
  default = 365
}
