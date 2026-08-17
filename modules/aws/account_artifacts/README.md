# AWS account artifacts

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
| [aws_codeartifact_domain.infra](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/codeartifact_domain) | resource |
| [aws_codeartifact_repository.sdk_candidate](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/codeartifact_repository) | resource |
| [aws_codeartifact_repository.sdk_stable](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/codeartifact_repository) | resource |
| [aws_kms_alias.codeartifact](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/kms_alias) | resource |
| [aws_kms_key.codeartifact](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/kms_key) | resource |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| <a name="input_aws_account_id"></a> [aws\_account\_id](#input\_aws\_account\_id) | n/a | `string` | n/a | yes |

## Outputs

| Name | Description |
| ---- | ----------- |
| <a name="output_domain_arn"></a> [domain\_arn](#output\_domain\_arn) | n/a |
| <a name="output_domain_name"></a> [domain\_name](#output\_domain\_name) | n/a |
| <a name="output_kms_key_arn"></a> [kms\_key\_arn](#output\_kms\_key\_arn) | n/a |
| <a name="output_sdk_candidate_arn"></a> [sdk\_candidate\_arn](#output\_sdk\_candidate\_arn) | n/a |
| <a name="output_sdk_candidate_repository"></a> [sdk\_candidate\_repository](#output\_sdk\_candidate\_repository) | n/a |
| <a name="output_sdk_stable_arn"></a> [sdk\_stable\_arn](#output\_sdk\_stable\_arn) | n/a |
| <a name="output_sdk_stable_repository"></a> [sdk\_stable\_repository](#output\_sdk\_stable\_repository) | n/a |
<!-- END_TF_DOCS -->
