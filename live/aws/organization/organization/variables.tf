variable "region" {
  type    = string
  default = "us-east-1"
}

variable "aws_profile" {
  type    = string
  default = "admin"
}

variable "catalog_file" {
  type    = string
  default = "../../../../catalog/catalog.json"
}

variable "github_owner" {
  type = string
}

variable "github_repo" {
  type = string
}

variable "github_oidc_provider_arn" {
  type        = string
  description = "Existing GitHub Actions OIDC provider ARN in the management account."
}

variable "control_plane_state_bucket" {
  type = string
}

variable "control_plane_lock_table" {
  type = string
}
