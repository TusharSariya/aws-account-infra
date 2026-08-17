# ECR repository

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
| [aws_ecr_lifecycle_policy.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecr_lifecycle_policy) | resource |
| [aws_ecr_repository.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecr_repository) | resource |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| <a name="input_force_delete"></a> [force\_delete](#input\_force\_delete) | Allow deleting the repo even if it still contains images. | `bool` | `false` | no |
| <a name="input_image_tag_mutability"></a> [image\_tag\_mutability](#input\_image\_tag\_mutability) | IMMUTABLE prevents overwriting an existing tag (recommended for reproducible deploys). | `string` | `"IMMUTABLE"` | no |
| <a name="input_kms_key_arn"></a> [kms\_key\_arn](#input\_kms\_key\_arn) | If set, images are encrypted with this KMS key; otherwise AES256. | `string` | `null` | no |
| <a name="input_max_images"></a> [max\_images](#input\_max\_images) | Keep at most this many images total (older ones expire). | `number` | `20` | no |
| <a name="input_name"></a> [name](#input\_name) | ECR repository name (e.g. graph-rag-query). | `string` | n/a | yes |
| <a name="input_preserve_oci_reference_artifacts"></a> [preserve\_oci\_reference\_artifacts](#input\_preserve\_oci\_reference\_artifacts) | Keep untagged OCI signature, SBOM, and provenance manifests; expire only image-* subjects by count. | `bool` | `false` | no |
| <a name="input_scan_on_push"></a> [scan\_on\_push](#input\_scan\_on\_push) | n/a | `bool` | `true` | no |
| <a name="input_tags"></a> [tags](#input\_tags) | n/a | `map(string)` | `{}` | no |
| <a name="input_untagged_expire_days"></a> [untagged\_expire\_days](#input\_untagged\_expire\_days) | n/a | `number` | `14` | no |

## Outputs

| Name | Description |
| ---- | ----------- |
| <a name="output_repository_arn"></a> [repository\_arn](#output\_repository\_arn) | n/a |
| <a name="output_repository_name"></a> [repository\_name](#output\_repository\_name) | n/a |
| <a name="output_repository_url"></a> [repository\_url](#output\_repository\_url) | e.g. 992382747916.dkr.ecr.us-east-1.amazonaws.com/graph-rag-query |
<!-- END_TF_DOCS -->
