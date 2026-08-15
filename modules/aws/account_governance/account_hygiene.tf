resource "aws_ebs_encryption_by_default" "this" {
  enabled = true
}

locals {
  create_alternate_contacts = trimspace(var.governance_contact_phone) != ""
}

resource "aws_account_alternate_contact" "security" {
  count = local.create_alternate_contacts ? 1 : 0

  alternate_contact_type = "SECURITY"
  email_address          = var.governance_alert_email
  name                   = var.governance_contact_name
  phone_number           = var.governance_contact_phone
  title                  = var.governance_contact_title
}

resource "aws_account_alternate_contact" "billing" {
  count = local.create_alternate_contacts ? 1 : 0

  alternate_contact_type = "BILLING"
  email_address          = var.governance_alert_email
  name                   = var.governance_contact_name
  phone_number           = var.governance_contact_phone
  title                  = var.governance_contact_title
}

resource "aws_account_alternate_contact" "operations" {
  count = local.create_alternate_contacts ? 1 : 0

  alternate_contact_type = "OPERATIONS"
  email_address          = var.governance_alert_email
  name                   = var.governance_contact_name
  phone_number           = var.governance_contact_phone
  title                  = var.governance_contact_title
}
