variable "region" {
  type    = string
  default = "us-east-1"
}

variable "aws_profile" {
  type        = string
  default     = "admin"
  description = "Source AWS profile used to create the backend (creds with admin rights)."
}

variable "state_bucket_name" {
  type    = string
  default = "tofu-state-992382747916-us-east-1"
}

variable "lock_table_name" {
  type    = string
  default = "tofu-locks"
}
