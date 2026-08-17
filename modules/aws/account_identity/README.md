# AWS account identity

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
| [aws_iam_openid_connect_provider.github](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_openid_connect_provider) | resource |
| [aws_iam_role.ecr_pull](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.github_apply](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.github_infra_ecr_push](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.github_lambda_package](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.github_plan](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.github_sdk_candidate](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.github_sdk_stable](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy.apply_state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.ecr_pull](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.github_infra_ecr_push](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.github_lambda_package](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.github_sdk_candidate](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.github_sdk_stable](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.plan_state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy_attachment.apply_admin](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_iam_role_policy_attachment.plan_readonly](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_rolesanywhere_profile.ecr_pull](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/rolesanywhere_profile) | resource |
| [aws_rolesanywhere_trust_anchor.ecr_pull](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/rolesanywhere_trust_anchor) | resource |
| [aws_s3_bucket.lambda_releases](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket) | resource |
| [aws_s3_bucket_lifecycle_configuration.lambda_releases](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_lifecycle_configuration) | resource |
| [aws_s3_bucket_public_access_block.lambda_releases](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_public_access_block) | resource |
| [aws_s3_bucket_server_side_encryption_configuration.lambda_releases](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_server_side_encryption_configuration) | resource |
| [aws_s3_bucket_versioning.lambda_releases](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_versioning) | resource |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| <a name="input_aws_account_id"></a> [aws\_account\_id](#input\_aws\_account\_id) | n/a | `string` | n/a | yes |
| <a name="input_codeartifact_domain_arn"></a> [codeartifact\_domain\_arn](#input\_codeartifact\_domain\_arn) | n/a | `string` | n/a | yes |
| <a name="input_codeartifact_domain_name"></a> [codeartifact\_domain\_name](#input\_codeartifact\_domain\_name) | n/a | `string` | n/a | yes |
| <a name="input_codeartifact_kms_key_arn"></a> [codeartifact\_kms\_key\_arn](#input\_codeartifact\_kms\_key\_arn) | n/a | `string` | n/a | yes |
| <a name="input_github_owner"></a> [github\_owner](#input\_github\_owner) | GitHub org/user that owns the CI repo (for OIDC trust). | `string` | n/a | yes |
| <a name="input_github_repo"></a> [github\_repo](#input\_github\_repo) | GitHub repo name (for OIDC trust). | `string` | n/a | yes |
| <a name="input_homelab_ca_certificate_pem"></a> [homelab\_ca\_certificate\_pem](#input\_homelab\_ca\_certificate\_pem) | PEM of the operator's CA certificate, registered as the Roles Anywhere trust anchor bundle. Operator-supplied via tfvars/CLI; never committed. | `string` | `""` | no |
| <a name="input_lock_table_name"></a> [lock\_table\_name](#input\_lock\_table\_name) | n/a | `string` | n/a | yes |
| <a name="input_region"></a> [region](#input\_region) | n/a | `string` | n/a | yes |
| <a name="input_sdk_candidate_repository_arn"></a> [sdk\_candidate\_repository\_arn](#input\_sdk\_candidate\_repository\_arn) | n/a | `string` | n/a | yes |
| <a name="input_sdk_candidate_repository_name"></a> [sdk\_candidate\_repository\_name](#input\_sdk\_candidate\_repository\_name) | n/a | `string` | n/a | yes |
| <a name="input_sdk_stable_repository_arn"></a> [sdk\_stable\_repository\_arn](#input\_sdk\_stable\_repository\_arn) | n/a | `string` | n/a | yes |
| <a name="input_sdk_stable_repository_name"></a> [sdk\_stable\_repository\_name](#input\_sdk\_stable\_repository\_name) | n/a | `string` | n/a | yes |
| <a name="input_state_bucket_name"></a> [state\_bucket\_name](#input\_state\_bucket\_name) | n/a | `string` | n/a | yes |

## Outputs

| Name | Description |
| ---- | ----------- |
| <a name="output_ecr_pull_profile_arn"></a> [ecr\_pull\_profile\_arn](#output\_ecr\_pull\_profile\_arn) | Roles Anywhere profile ARN the node's aws\_signing\_helper requests against. null until a CA cert is supplied. |
| <a name="output_ecr_pull_role_arn"></a> [ecr\_pull\_role\_arn](#output\_ecr\_pull\_role\_arn) | IAM role the homelab nodes assume via Roles Anywhere to pull ECR images. null until a CA cert is supplied. |
| <a name="output_ecr_pull_trust_anchor_arn"></a> [ecr\_pull\_trust\_anchor\_arn](#output\_ecr\_pull\_trust\_anchor\_arn) | Roles Anywhere trust anchor ARN (CA registered for the homelab ECR-pull identity). null until a CA cert is supplied. |
| <a name="output_github_apply_role_arn"></a> [github\_apply\_role\_arn](#output\_github\_apply\_role\_arn) | role-to-assume for the tofu-apply workflow (main). |
| <a name="output_github_infra_ecr_push_role_arn"></a> [github\_infra\_ecr\_push\_role\_arn](#output\_github\_infra\_ecr\_push\_role\_arn) | role-to-assume for .github/workflows/ecr-push.yml (apps/ecr images). |
| <a name="output_github_lambda_candidate_role_arn"></a> [github\_lambda\_candidate\_role\_arn](#output\_github\_lambda\_candidate\_role\_arn) | role-to-assume on PRs for candidate/<name>/<sha>.zip uploads. |
| <a name="output_github_lambda_stable_role_arn"></a> [github\_lambda\_stable\_role\_arn](#output\_github\_lambda\_stable\_role\_arn) | role-to-assume on main for stable/<name>/<sha>.zip uploads. |
| <a name="output_github_oidc_provider_arn"></a> [github\_oidc\_provider\_arn](#output\_github\_oidc\_provider\_arn) | n/a |
| <a name="output_github_plan_role_arn"></a> [github\_plan\_role\_arn](#output\_github\_plan\_role\_arn) | role-to-assume for the tofu-plan workflow (PRs). |
| <a name="output_github_sdk_candidate_role_arn"></a> [github\_sdk\_candidate\_role\_arn](#output\_github\_sdk\_candidate\_role\_arn) | role-to-assume for SDK candidate publishes to CodeArtifact sdk-candidate. |
| <a name="output_github_sdk_stable_role_arn"></a> [github\_sdk\_stable\_role\_arn](#output\_github\_sdk\_stable\_role\_arn) | role-to-assume for SDK stable publishes (GitHub Environment sdk). |
| <a name="output_lambda_releases_bucket"></a> [lambda\_releases\_bucket](#output\_lambda\_releases\_bucket) | Shared Lambda zip releases bucket (candidate/ and stable/ prefixes). |
<!-- END_TF_DOCS -->
