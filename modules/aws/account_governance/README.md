# AWS account governance

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
| ---- | ------- |
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | >= 1.8 |
| <a name="requirement_aws"></a> [aws](#requirement\_aws) | >= 5.0 |

## Providers

| Name | Version |
| ---- | ------- |
| <a name="provider_aws"></a> [aws](#provider\_aws) | >= 5.0 |

## Resources

| Name | Type |
| ---- | ---- |
| [aws_accessanalyzer_analyzer.external](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/accessanalyzer_analyzer) | resource |
| [aws_account_alternate_contact.billing](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/account_alternate_contact) | resource |
| [aws_account_alternate_contact.operations](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/account_alternate_contact) | resource |
| [aws_account_alternate_contact.security](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/account_alternate_contact) | resource |
| [aws_budgets_budget.monthly](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/budgets_budget) | resource |
| [aws_ce_anomaly_monitor.services](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ce_anomaly_monitor) | resource |
| [aws_ce_anomaly_subscription.services](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ce_anomaly_subscription) | resource |
| [aws_cloudformation_stack.budget_reports](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudformation_stack) | resource |
| [aws_cloudtrail.account](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudtrail) | resource |
| [aws_cloudwatch_event_rule.audit_tamper](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_rule) | resource |
| [aws_cloudwatch_event_rule.console_login_without_mfa](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_rule) | resource |
| [aws_cloudwatch_event_rule.guardduty_findings](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_rule) | resource |
| [aws_cloudwatch_event_rule.iam_key_and_user](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_rule) | resource |
| [aws_cloudwatch_event_rule.root_activity](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_rule) | resource |
| [aws_cloudwatch_event_rule.s3_bucket_policy](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_rule) | resource |
| [aws_cloudwatch_event_target.audit_tamper](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_target) | resource |
| [aws_cloudwatch_event_target.console_login_without_mfa](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_target) | resource |
| [aws_cloudwatch_event_target.guardduty_findings](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_target) | resource |
| [aws_cloudwatch_event_target.iam_key_and_user](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_target) | resource |
| [aws_cloudwatch_event_target.root_activity](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_target) | resource |
| [aws_cloudwatch_event_target.s3_bucket_policy](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_target) | resource |
| [aws_ebs_encryption_by_default.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ebs_encryption_by_default) | resource |
| [aws_guardduty_detector.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/guardduty_detector) | resource |
| [aws_guardduty_detector_feature.disabled](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/guardduty_detector_feature) | resource |
| [aws_guardduty_detector_feature.runtime_monitoring](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/guardduty_detector_feature) | resource |
| [aws_iam_account_password_policy.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_account_password_policy) | resource |
| [aws_s3_account_public_access_block.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_account_public_access_block) | resource |
| [aws_s3_bucket.cloudtrail](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket) | resource |
| [aws_s3_bucket_lifecycle_configuration.cloudtrail](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_lifecycle_configuration) | resource |
| [aws_s3_bucket_policy.cloudtrail](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_policy) | resource |
| [aws_s3_bucket_public_access_block.cloudtrail](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_public_access_block) | resource |
| [aws_s3_bucket_server_side_encryption_configuration.cloudtrail](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_server_side_encryption_configuration) | resource |
| [aws_s3_bucket_versioning.cloudtrail](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_versioning) | resource |
| [aws_sns_topic.security_alerts](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sns_topic) | resource |
| [aws_sns_topic_policy.security_alerts](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sns_topic_policy) | resource |
| [aws_sns_topic_subscription.security_alerts_email](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sns_topic_subscription) | resource |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| <a name="input_aws_account_id"></a> [aws\_account\_id](#input\_aws\_account\_id) | n/a | `string` | n/a | yes |
| <a name="input_budget_monthly_limit_usd"></a> [budget\_monthly\_limit\_usd](#input\_budget\_monthly\_limit\_usd) | Monthly cost budget threshold in USD. | `string` | n/a | yes |
| <a name="input_budget_notification_email"></a> [budget\_notification\_email](#input\_budget\_notification\_email) | Email notified when the budget alarm trips. | `string` | n/a | yes |
| <a name="input_governance_alert_email"></a> [governance\_alert\_email](#input\_governance\_alert\_email) | Destination for budget reports, cost-anomaly alerts, GuardDuty, and EventBridge security mail. | `string` | n/a | yes |
| <a name="input_governance_contact_name"></a> [governance\_contact\_name](#input\_governance\_contact\_name) | Display name for account alternate contacts (billing, operations, security). | `string` | `"Tushar Sariya"` | no |
| <a name="input_governance_contact_phone"></a> [governance\_contact\_phone](#input\_governance\_contact\_phone) | E.164 phone for account alternate contacts. Empty skips creating those contacts. | `string` | `""` | no |
| <a name="input_governance_contact_title"></a> [governance\_contact\_title](#input\_governance\_contact\_title) | Title for account alternate contacts. | `string` | `"Account owner"` | no |
| <a name="input_region"></a> [region](#input\_region) | n/a | `string` | n/a | yes |

## Outputs

| Name | Description |
| ---- | ----------- |
| <a name="output_budget_reports_stack_id"></a> [budget\_reports\_stack\_id](#output\_budget\_reports\_stack\_id) | Nested stack that emails daily, weekly, and monthly Cost Explorer summaries to governance\_alert\_email. |
| <a name="output_cloudtrail_arn"></a> [cloudtrail\_arn](#output\_cloudtrail\_arn) | Multi-region management-event trail. Confirm SNS opt-in mail for security alerts. |
| <a name="output_guardduty_detector_id"></a> [guardduty\_detector\_id](#output\_guardduty\_detector\_id) | n/a |
| <a name="output_security_alerts_topic_arn"></a> [security\_alerts\_topic\_arn](#output\_security\_alerts\_topic\_arn) | SNS topic for GuardDuty findings and EventBridge IAM/root alerts. Confirm the subscription email. |
<!-- END_TF_DOCS -->
