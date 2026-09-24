variable "aws_account_id" { type = string }
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
variable "artifact_key" {
  type        = string
  description = "Immutable stable/technology-digest/<sha256>.zip in the existing release bucket."
  validation {
    condition     = can(regex("^stable/technology-digest/[a-f0-9]{64}\\.zip$", var.artifact_key))
    error_message = "Use a content-addressed stable digest artifact."
  }
}
variable "artifact_sha256" {
  type        = string
  description = "Base64 SHA256 of the exact release zip."
}
variable "sender" {
  type    = string
  default = "tushar.97@hotmail.com"
}
variable "recipient" {
  type    = string
  default = "tushar.97@hotmail.com"
}
variable "schedules_enabled" {
  type    = bool
  default = false
}
