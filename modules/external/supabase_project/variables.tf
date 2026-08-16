variable "organization_id" {
  type = string
}

variable "project_name" {
  type = string
}

variable "region" {
  type = string
}

variable "database_password" {
  type      = string
  sensitive = true
}

variable "site_url" {
  type = string
}

variable "redirect_urls" {
  type = list(string)
}
