provider "aws" {
  region = var.region

  assume_role {
    role_arn     = "arn:aws:iam::${var.account_id}:role/OrganizationAccountAccessRole"
    session_name = "account-bootstrap"
  }

  default_tags {
    tags = {
      managed_by  = "opentofu"
      service     = var.service_id
      environment = var.environment
      stack       = "account-bootstrap"
    }
  }
}

module "baseline" {
  source = "../../../../modules/aws/vended_account_baseline"

  account_id        = var.account_id
  region            = var.region
  service_id        = var.service_id
  environment       = var.environment
  budget_usd        = var.budget_usd
  budget_emails     = var.budget_emails
  github_owner      = var.github_owner
  github_repo       = var.github_repo
  state_bucket_name = var.state_bucket_name
  apply_policy_json = var.apply_policy_json
}

output "bootstrap" {
  value = module.baseline
}
