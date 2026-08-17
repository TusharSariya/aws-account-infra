# Module distribution

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
| [aws_iam_role.publisher](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy.publisher](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_s3_bucket.modules](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket) | resource |
| [aws_s3_bucket_object_lock_configuration.modules](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_object_lock_configuration) | resource |
| [aws_s3_bucket_policy.modules](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_policy) | resource |
| [aws_s3_bucket_public_access_block.modules](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_public_access_block) | resource |
| [aws_s3_bucket_server_side_encryption_configuration.modules](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_server_side_encryption_configuration) | resource |
| [aws_s3_bucket_versioning.modules](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_versioning) | resource |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| <a name="input_bucket_name"></a> [bucket\_name](#input\_bucket\_name) | n/a | `string` | n/a | yes |
| <a name="input_github_oidc_provider_arn"></a> [github\_oidc\_provider\_arn](#input\_github\_oidc\_provider\_arn) | n/a | `string` | n/a | yes |
| <a name="input_github_owner"></a> [github\_owner](#input\_github\_owner) | n/a | `string` | n/a | yes |
| <a name="input_github_repo"></a> [github\_repo](#input\_github\_repo) | n/a | `string` | n/a | yes |
| <a name="input_organization_id"></a> [organization\_id](#input\_organization\_id) | n/a | `string` | n/a | yes |
| <a name="input_retention_days"></a> [retention\_days](#input\_retention\_days) | n/a | `number` | `365` | no |

## Outputs

| Name | Description |
| ---- | ----------- |
| <a name="output_bucket_name"></a> [bucket\_name](#output\_bucket\_name) | n/a |
| <a name="output_publisher_role_arn"></a> [publisher\_role\_arn](#output\_publisher\_role\_arn) | n/a |
<!-- END_TF_DOCS -->
