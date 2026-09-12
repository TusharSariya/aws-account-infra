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

variable "create_backup_identity" {
  type        = bool
  default     = true
  description = "Create the optional Roles Anywhere uploader. Turning off an existing identity destroys it; use backup_identity_enabled=false to suspend sessions instead."
}

variable "backup_ca_certificate_pem" {
  default     = ""
  type        = string
  nullable    = false
  description = "Public backup CA certificate, required only when create_backup_identity is true. Never supply a private key."
  validation {
    condition     = !var.create_backup_identity || (startswith(trimspace(var.backup_ca_certificate_pem), "-----BEGIN CERTIFICATE-----") && endswith(trimspace(var.backup_ca_certificate_pem), "-----END CERTIFICATE-----") && !strcontains(var.backup_ca_certificate_pem, "PRIVATE KEY"))
    error_message = "Supply a public PEM certificate, never a private key or an empty value."
  }
}

variable "backup_certificate_common_name" {
  type        = string
  nullable    = false
  description = "Exact permitted leaf certificate CN. Change identity on revocation; old certificates then cannot request new sessions."
  validation {
    condition     = can(regex("^homelab-backup-uploader-[a-z0-9-]{1,32}$", var.backup_certificate_common_name))
    error_message = "Use homelab-backup-uploader- followed by 1-32 lowercase letters, digits or hyphens."
  }
}

variable "backup_identity_enabled" {
  type        = bool
  default     = true
  description = "Enable the backup trust anchor/profile. False stops new sessions; existing credentials remain valid until expiry."
}
