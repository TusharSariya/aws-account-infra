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

variable "schedule_enabled" {
  description = "Enable hourly refresh after verified authentication and initial sync."
  type        = bool
  default     = false
}

variable "history_enabled" {
  description = "Enable bounded historical batches after a verified initial run."
  type        = bool
  default     = false
}

variable "measured_planning_margin" {
  description = "Fractional planning margin for supported measured/profile and historical estimates."
  type        = number
  default     = 0.2
  validation {
    condition     = var.measured_planning_margin >= 0 && var.measured_planning_margin <= 1
    error_message = "Planning margin must be between zero and one."
  }
}

variable "wide_planning_margin" {
  description = "Fractional planning margin for default, sparse, extrapolated, coarse or incomplete estimates."
  type        = number
  default     = 0.4
  validation {
    condition     = var.wide_planning_margin >= 0 && var.wide_planning_margin <= 1
    error_message = "Planning margin must be between zero and one."
  }
}

variable "default_power_curve" {
  description = "Assumed 100 W FTP-based default: duration seconds and watts, never measured fitness."
  type        = list(tuple([number, number]))
  default     = [[300, 120], [1200, 105], [3600, 100], [7200, 90], [14400, 80]]
  validation {
    condition = length(var.default_power_curve) >= 2 && alltrue([
      for i, point in var.default_power_curve : point[0] > 0 && point[1] > 0 && (
        i == 0 ? true : point[0] > var.default_power_curve[i - 1][0] && point[1] <= var.default_power_curve[i - 1][1]
      )
    ])
    error_message = "Provide at least two positive points with increasing duration and non-increasing power."
  }
}
