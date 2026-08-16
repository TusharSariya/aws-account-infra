variable "service_id" {
  type = string
}

variable "purge" {
  type    = bool
  default = false
}

variable "database_password" {
  type      = string
  sensitive = true
}

variable "catalog_file" {
  type    = string
  default = "../../../catalog/catalog.json"
}
