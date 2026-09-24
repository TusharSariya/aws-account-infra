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
    condition     = contains(["ymca", "paul_reynolds", "iracing"], var.calendar_source)
    error_message = "Choose exactly one supported calendar source."
  }
}

variable "package_builder" {
  type    = string
  default = "scripts/swim-package.py"
}
variable "handlers" {
  type    = map(string)
  default = { sync = "swim_calendar.handlers.sync", feed = "swim_calendar.handlers.feed" }
}
variable "route" {
  type    = string
  default = "/calendars/swimming.ics"
}
variable "refresh_schedule" {
  type    = string
  default = "cron(0 3 * * ? *)"
}
variable "refresh_name_suffix" {
  type    = string
  default = "daily"
}
variable "health_threshold_seconds" {
  type    = number
  default = 129600
}
variable "sync_object_keys" {
  type    = list(string)
  default = ["current.json", "lease.json"]
}
variable "memory_sizes" {
  type    = map(number)
  default = { sync = 256, feed = 256 }
}
variable "sync_timeout" {
  type    = number
  default = 600
}
