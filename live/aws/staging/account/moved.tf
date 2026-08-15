# Address remaps for the account root split. Same state key; no AWS recreation.

# --- artifacts ---
moved {
  from = aws_kms_key.codeartifact
  to   = module.artifacts.aws_kms_key.codeartifact
}

moved {
  from = aws_kms_alias.codeartifact
  to   = module.artifacts.aws_kms_alias.codeartifact
}

moved {
  from = aws_codeartifact_domain.infra
  to   = module.artifacts.aws_codeartifact_domain.infra
}

moved {
  from = aws_codeartifact_repository.sdk_candidate
  to   = module.artifacts.aws_codeartifact_repository.sdk_candidate
}

moved {
  from = aws_codeartifact_repository.sdk_stable
  to   = module.artifacts.aws_codeartifact_repository.sdk_stable
}

# --- identity ---
moved {
  from = aws_iam_openid_connect_provider.github
  to   = module.identity.aws_iam_openid_connect_provider.github
}

moved {
  from = aws_iam_role.github_plan
  to   = module.identity.aws_iam_role.github_plan
}

moved {
  from = aws_iam_role_policy_attachment.plan_readonly
  to   = module.identity.aws_iam_role_policy_attachment.plan_readonly
}

moved {
  from = aws_iam_role_policy.plan_state
  to   = module.identity.aws_iam_role_policy.plan_state
}

moved {
  from = aws_iam_role.github_apply
  to   = module.identity.aws_iam_role.github_apply
}

moved {
  from = aws_iam_role_policy_attachment.apply_admin
  to   = module.identity.aws_iam_role_policy_attachment.apply_admin
}

moved {
  from = aws_iam_role_policy.apply_state
  to   = module.identity.aws_iam_role_policy.apply_state
}

moved {
  from = aws_iam_role.github_infra_ecr_push
  to   = module.identity.aws_iam_role.github_infra_ecr_push
}

moved {
  from = aws_iam_role_policy.github_infra_ecr_push
  to   = module.identity.aws_iam_role_policy.github_infra_ecr_push
}

moved {
  from = aws_s3_bucket.lambda_releases
  to   = module.identity.aws_s3_bucket.lambda_releases
}

moved {
  from = aws_s3_bucket_versioning.lambda_releases
  to   = module.identity.aws_s3_bucket_versioning.lambda_releases
}

moved {
  from = aws_s3_bucket_server_side_encryption_configuration.lambda_releases
  to   = module.identity.aws_s3_bucket_server_side_encryption_configuration.lambda_releases
}

moved {
  from = aws_s3_bucket_public_access_block.lambda_releases
  to   = module.identity.aws_s3_bucket_public_access_block.lambda_releases
}

moved {
  from = aws_s3_bucket_lifecycle_configuration.lambda_releases
  to   = module.identity.aws_s3_bucket_lifecycle_configuration.lambda_releases
}

moved {
  from = aws_iam_role.github_lambda_package
  to   = module.identity.aws_iam_role.github_lambda_package
}

moved {
  from = aws_iam_role_policy.github_lambda_package
  to   = module.identity.aws_iam_role_policy.github_lambda_package
}

moved {
  from = aws_iam_role.github_sdk_candidate
  to   = module.identity.aws_iam_role.github_sdk_candidate
}

moved {
  from = aws_iam_role.github_sdk_stable
  to   = module.identity.aws_iam_role.github_sdk_stable
}

moved {
  from = aws_iam_role_policy.github_sdk_candidate
  to   = module.identity.aws_iam_role_policy.github_sdk_candidate
}

moved {
  from = aws_iam_role_policy.github_sdk_stable
  to   = module.identity.aws_iam_role_policy.github_sdk_stable
}

moved {
  from = aws_rolesanywhere_trust_anchor.ecr_pull
  to   = module.identity.aws_rolesanywhere_trust_anchor.ecr_pull
}

moved {
  from = aws_iam_role.ecr_pull
  to   = module.identity.aws_iam_role.ecr_pull
}

moved {
  from = aws_iam_role_policy.ecr_pull
  to   = module.identity.aws_iam_role_policy.ecr_pull
}

moved {
  from = aws_rolesanywhere_profile.ecr_pull
  to   = module.identity.aws_rolesanywhere_profile.ecr_pull
}

# --- governance ---
moved {
  from = aws_s3_account_public_access_block.this
  to   = module.governance.aws_s3_account_public_access_block.this
}

moved {
  from = aws_iam_account_password_policy.this
  to   = module.governance.aws_iam_account_password_policy.this
}

moved {
  from = aws_ebs_encryption_by_default.this
  to   = module.governance.aws_ebs_encryption_by_default.this
}

moved {
  from = aws_account_alternate_contact.security
  to   = module.governance.aws_account_alternate_contact.security
}

moved {
  from = aws_account_alternate_contact.billing
  to   = module.governance.aws_account_alternate_contact.billing
}

moved {
  from = aws_account_alternate_contact.operations
  to   = module.governance.aws_account_alternate_contact.operations
}

moved {
  from = aws_s3_bucket.cloudtrail
  to   = module.governance.aws_s3_bucket.cloudtrail
}

moved {
  from = aws_s3_bucket_versioning.cloudtrail
  to   = module.governance.aws_s3_bucket_versioning.cloudtrail
}

moved {
  from = aws_s3_bucket_server_side_encryption_configuration.cloudtrail
  to   = module.governance.aws_s3_bucket_server_side_encryption_configuration.cloudtrail
}

moved {
  from = aws_s3_bucket_public_access_block.cloudtrail
  to   = module.governance.aws_s3_bucket_public_access_block.cloudtrail
}

moved {
  from = aws_s3_bucket_lifecycle_configuration.cloudtrail
  to   = module.governance.aws_s3_bucket_lifecycle_configuration.cloudtrail
}

moved {
  from = aws_s3_bucket_policy.cloudtrail
  to   = module.governance.aws_s3_bucket_policy.cloudtrail
}

moved {
  from = aws_cloudtrail.account
  to   = module.governance.aws_cloudtrail.account
}

moved {
  from = aws_guardduty_detector.this
  to   = module.governance.aws_guardduty_detector.this
}

moved {
  from = aws_guardduty_detector_feature.disabled
  to   = module.governance.aws_guardduty_detector_feature.disabled
}

moved {
  from = aws_guardduty_detector_feature.runtime_monitoring
  to   = module.governance.aws_guardduty_detector_feature.runtime_monitoring
}

moved {
  from = aws_cloudwatch_event_rule.guardduty_findings
  to   = module.governance.aws_cloudwatch_event_rule.guardduty_findings
}

moved {
  from = aws_cloudwatch_event_target.guardduty_findings
  to   = module.governance.aws_cloudwatch_event_target.guardduty_findings
}

moved {
  from = aws_sns_topic.security_alerts
  to   = module.governance.aws_sns_topic.security_alerts
}

moved {
  from = aws_sns_topic_policy.security_alerts
  to   = module.governance.aws_sns_topic_policy.security_alerts
}

moved {
  from = aws_sns_topic_subscription.security_alerts_email
  to   = module.governance.aws_sns_topic_subscription.security_alerts_email
}

moved {
  from = aws_cloudwatch_event_rule.root_activity
  to   = module.governance.aws_cloudwatch_event_rule.root_activity
}

moved {
  from = aws_cloudwatch_event_target.root_activity
  to   = module.governance.aws_cloudwatch_event_target.root_activity
}

moved {
  from = aws_cloudwatch_event_rule.console_login_without_mfa
  to   = module.governance.aws_cloudwatch_event_rule.console_login_without_mfa
}

moved {
  from = aws_cloudwatch_event_target.console_login_without_mfa
  to   = module.governance.aws_cloudwatch_event_target.console_login_without_mfa
}

moved {
  from = aws_cloudwatch_event_rule.iam_key_and_user
  to   = module.governance.aws_cloudwatch_event_rule.iam_key_and_user
}

moved {
  from = aws_cloudwatch_event_target.iam_key_and_user
  to   = module.governance.aws_cloudwatch_event_target.iam_key_and_user
}

moved {
  from = aws_cloudwatch_event_rule.audit_tamper
  to   = module.governance.aws_cloudwatch_event_rule.audit_tamper
}

moved {
  from = aws_cloudwatch_event_target.audit_tamper
  to   = module.governance.aws_cloudwatch_event_target.audit_tamper
}

moved {
  from = aws_cloudwatch_event_rule.s3_bucket_policy
  to   = module.governance.aws_cloudwatch_event_rule.s3_bucket_policy
}

moved {
  from = aws_cloudwatch_event_target.s3_bucket_policy
  to   = module.governance.aws_cloudwatch_event_target.s3_bucket_policy
}

moved {
  from = aws_accessanalyzer_analyzer.external
  to   = module.governance.aws_accessanalyzer_analyzer.external
}

moved {
  from = aws_budgets_budget.monthly
  to   = module.governance.aws_budgets_budget.monthly
}

moved {
  from = aws_cloudformation_stack.budget_reports
  to   = module.governance.aws_cloudformation_stack.budget_reports
}

moved {
  from = aws_ce_anomaly_monitor.services
  to   = module.governance.aws_ce_anomaly_monitor.services
}

moved {
  from = aws_ce_anomaly_subscription.services
  to   = module.governance.aws_ce_anomaly_subscription.services
}
