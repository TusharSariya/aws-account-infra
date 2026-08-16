provider "aws" {
  region  = var.region
  profile = var.aws_profile != "" ? var.aws_profile : null

  default_tags {
    tags = {
      managed_by = "opentofu"
      repo       = "aws-account-infra"
      stack      = "account-vending"
    }
  }
}

locals {
  catalog = jsondecode(file(var.catalog_file))
  service = local.catalog.services[var.service_id]
  account = local.service.accounts[var.environment]
}

resource "aws_organizations_account" "this" {
  name                       = local.account.name
  email                      = local.account.root_email
  parent_id                  = var.parent_ou_id
  role_name                  = "OrganizationAccountAccessRole"
  iam_user_access_to_billing = "ALLOW"
  close_on_deletion          = false

  tags = {
    service     = var.service_id
    environment = var.environment
    lifecycle   = local.account.lifecycle
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [role_name]

    precondition {
      condition     = local.account.lifecycle == "active" || startswith(local.account.ou_path, "Suspended/")
      error_message = "Retired accounts must be moved to the Suspended OU before applying."
    }
  }

  timeouts {
    create = "30m"
    update = "30m"
  }
}

output "account" {
  value = {
    service_id  = var.service_id
    environment = var.environment
    account_id  = aws_organizations_account.this.id
    name        = aws_organizations_account.this.name
    ou_path     = local.account.ou_path
    region      = local.account.region
  }
}
