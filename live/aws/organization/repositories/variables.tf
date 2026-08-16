variable "github_owner" {
  type = string
}

variable "service_id" {
  type = string
}

variable "catalog_file" {
  type    = string
  default = "../../../../catalog/catalog.json"
}

variable "enable_protection" {
  type        = bool
  default     = true
  description = "Keep false until filtered history has established main for migration repositories."
}

variable "required_status_checks" {
  type    = list(string)
  default = ["test", "tofu-plan"]
}
