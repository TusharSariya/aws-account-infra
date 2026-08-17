# Vended account baseline

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
| ---- | ------- |
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | >= 1.8 |
| <a name="requirement_aws"></a> [aws](#requirement\_aws) | ~> 6.5 |

## Providers

| Name | Version |
| ---- | ------- |
| <a name="provider_aws"></a> [aws](#provider\_aws) | ~> 6.5 |

## Resources

| Name | Type |
| ---- | ---- |
| [aws_budgets_budget.monthly](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/budgets_budget) | resource |
| [aws_ce_anomaly_monitor.services](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ce_anomaly_monitor) | resource |
| [aws_ce_anomaly_subscription.services](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ce_anomaly_subscription) | resource |
| [aws_iam_openid_connect_provider.github](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_openid_connect_provider) | resource |
| [aws_iam_policy.service_apply](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_policy) | resource |
| [aws_iam_role.github_apply](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.github_package](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.github_plan](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy.apply_state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.package](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.plan_boundary](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy_attachment.apply](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_iam_role_policy_attachment.plan_readonly](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_s3_account_public_access_block.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_account_public_access_block) | resource |
| [aws_s3_bucket.lambda_releases](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket) | resource |
| [aws_s3_bucket.state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket) | resource |
| [aws_s3_bucket_lifecycle_configuration.lambda_releases](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_lifecycle_configuration) | resource |
| [aws_s3_bucket_lifecycle_configuration.state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_lifecycle_configuration) | resource |
| [aws_s3_bucket_policy.state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_policy) | resource |
| [aws_s3_bucket_public_access_block.lambda_releases](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_public_access_block) | resource |
| [aws_s3_bucket_public_access_block.state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_public_access_block) | resource |
| [aws_s3_bucket_server_side_encryption_configuration.lambda_releases](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_server_side_encryption_configuration) | resource |
| [aws_s3_bucket_server_side_encryption_configuration.state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_server_side_encryption_configuration) | resource |
| [aws_s3_bucket_versioning.lambda_releases](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_versioning) | resource |
| [aws_s3_bucket_versioning.state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_versioning) | resource |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| <a name="input_account_id"></a> [account\_id](#input\_account\_id) | n/a | `string` | n/a | yes |
| <a name="input_apply_policy_json"></a> [apply\_policy\_json](#input\_apply\_policy\_json) | Service-specific deployment permissions. Generic AdministratorAccess is intentionally unsupported. | `string` | n/a | yes |
| <a name="input_budget_emails"></a> [budget\_emails](#input\_budget\_emails) | n/a | `list(string)` | n/a | yes |
| <a name="input_budget_usd"></a> [budget\_usd](#input\_budget\_usd) | n/a | `number` | n/a | yes |
| <a name="input_cost_anomaly_threshold_usd"></a> [cost\_anomaly\_threshold\_usd](#input\_cost\_anomaly\_threshold\_usd) | Minimum absolute impact in USD before sending a cost anomaly alert. | `number` | `5` | no |
| <a name="input_environment"></a> [environment](#input\_environment) | n/a | `string` | n/a | yes |
| <a name="input_github_owner"></a> [github\_owner](#input\_github\_owner) | n/a | `string` | n/a | yes |
| <a name="input_github_repo"></a> [github\_repo](#input\_github\_repo) | n/a | `string` | n/a | yes |
| <a name="input_region"></a> [region](#input\_region) | n/a | `string` | n/a | yes |
| <a name="input_service_id"></a> [service\_id](#input\_service\_id) | n/a | `string` | n/a | yes |
| <a name="input_state_bucket_name"></a> [state\_bucket\_name](#input\_state\_bucket\_name) | n/a | `string` | n/a | yes |

## Outputs

| Name | Description |
| ---- | ----------- |
| <a name="output_apply_role_arn"></a> [apply\_role\_arn](#output\_apply\_role\_arn) | n/a |
| <a name="output_lambda_releases_bucket"></a> [lambda\_releases\_bucket](#output\_lambda\_releases\_bucket) | n/a |
| <a name="output_package_role_arn"></a> [package\_role\_arn](#output\_package\_role\_arn) | n/a |
| <a name="output_plan_role_arn"></a> [plan\_role\_arn](#output\_plan\_role\_arn) | n/a |
| <a name="output_state_bucket_name"></a> [state\_bucket\_name](#output\_state\_bucket\_name) | n/a |
<!-- END_TF_DOCS -->
