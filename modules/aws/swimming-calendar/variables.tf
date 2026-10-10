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
    condition     = contains(["ymca", "paul_reynolds", "iracing", "zwift"], var.calendar_source)
    error_message = "Choose exactly one supported calendar source."
  }
}

variable "function_environment" {
  description = "Additional non-secret configuration per runtime function."
  type        = map(map(string))
  default     = {}
}

variable "sync_parameter_reads" {
  description = "SSM parameter names populated outside OpenTofu; readable only by sync."
  type        = list(string)
  default     = []
  validation {
    condition     = alltrue([for name in var.sync_parameter_reads : startswith(name, "/") && length(regexall("[:*?]", name)) == 0])
    error_message = "Use exact, absolute, unversioned SSM parameter paths."
  }
}

variable "sync_parameter_writes" {
  description = "Subset of sync parameters containing renewable tokens."
  type        = list(string)
  default     = []
  validation {
    condition     = alltrue([for name in var.sync_parameter_writes : contains(var.sync_parameter_reads, name)])
    error_message = "Writable parameters must also be readable by sync."
  }
}

variable "schedule_enabled" {
  description = "Enable refresh and health schedules after initialization."
  type        = bool
  default     = true
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

variable "refresh_timezone" {
  type    = string
  default = "America/St_Johns"
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

variable "oauth_parameters" {
  description = "Optional SSM SecureString parameter names. Values are populated outside OpenTofu."
  type = object({
    client_name         = string
    token_name          = string
    maintenance_enabled = optional(bool, false)
  })
  default = null
  validation {
    condition     = var.oauth_parameters == null ? true : var.oauth_parameters.client_name != var.oauth_parameters.token_name
    error_message = "Client credentials and tokens must use separate parameters."
  }
  validation {
    condition = var.oauth_parameters == null ? true : alltrue([
      for name in [var.oauth_parameters.client_name, var.oauth_parameters.token_name] :
      startswith(name, "/") && length(regexall(":", name)) == 0
    ])
    error_message = "Use absolute, unversioned SSM parameter paths."
  }
}

variable "additional_routes" {
  description = "Additional public calendar GET paths handled by the same feed Lambda."
  type        = set(string)
  default     = []
  validation {
    condition     = alltrue([for route in var.additional_routes : startswith(route, "/calendars/") && endswith(route, ".ics") && length(regexall("[{}*?]", route)) == 0 && route != var.route])
    error_message = "Additional routes must be distinct, literal /calendars/*.ics paths."
  }
}

variable "feed_object_keys" {
  description = "Private objects read by feed health checks; only current.json is served."
  type        = list(string)
  default     = ["current.json"]
}
