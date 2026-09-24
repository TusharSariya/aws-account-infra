variable "app_root" { type = string }
variable "zip_bucket_name" { type = string }
variable "aws_account_id" { type = string }
variable "region" { type = string }
variable "service_name" { type = string }
variable "calendar_name" { type = string }
variable "uid_domain" { type = string }
variable "calendar_source" {
  type = string
  validation {
    condition     = contains(["ymca", "paul_reynolds"], var.calendar_source)
    error_message = "Choose exactly one supported swimming source."
  }
}
