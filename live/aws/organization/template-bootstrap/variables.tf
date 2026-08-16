variable "github_owner" {
  type = string
}

variable "repository_name" {
  type    = string
  default = "service-stack-template"
}

variable "enable_protection" {
  type        = bool
  default     = false
  description = "Enable only after the reviewed seed commit creates main and emits the test context."
}
