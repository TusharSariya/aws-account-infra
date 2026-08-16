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

variable "service_id" {
  type = string
}

variable "environment" {
  type = string
}

variable "parent_ou_id" {
  type        = string
  description = "OU identifier from the organization root output. Retired accounts must use Suspended/Accounts."
}
