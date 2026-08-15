module "artifacts" {
  source = "../../../../modules/aws/account_artifacts"

  aws_account_id = var.aws_account_id
}

module "identity" {
  source = "../../../../modules/aws/account_identity"

  aws_account_id             = var.aws_account_id
  region                     = var.region
  github_owner               = var.github_owner
  github_repo                = var.github_repo
  state_bucket_name          = var.state_bucket_name
  lock_table_name            = var.lock_table_name
  homelab_ca_certificate_pem = var.homelab_ca_certificate_pem

  codeartifact_domain_arn       = module.artifacts.domain_arn
  codeartifact_domain_name      = module.artifacts.domain_name
  sdk_candidate_repository_arn  = module.artifacts.sdk_candidate_arn
  sdk_candidate_repository_name = module.artifacts.sdk_candidate_repository
  sdk_stable_repository_arn     = module.artifacts.sdk_stable_arn
  sdk_stable_repository_name    = module.artifacts.sdk_stable_repository
  codeartifact_kms_key_arn      = module.artifacts.kms_key_arn
}

module "governance" {
  source = "../../../../modules/aws/account_governance"

  aws_account_id            = var.aws_account_id
  region                    = var.region
  budget_monthly_limit_usd  = var.budget_monthly_limit_usd
  budget_notification_email = var.budget_notification_email
  governance_alert_email    = var.governance_alert_email
  governance_contact_name   = var.governance_contact_name
  governance_contact_title  = var.governance_contact_title
  governance_contact_phone  = var.governance_contact_phone
}
