# Encrypted S3 bucket

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

## Modules

| Name | Source | Version |
| ---- | ------ | ------- |
| <a name="module_bucket"></a> [bucket](#module\_bucket) | terraform-aws-modules/s3-bucket/aws | 5.8.0 |
| <a name="module_kms"></a> [kms](#module\_kms) | terraform-aws-modules/kms/aws | 4.1.0 |

## Resources

| Name | Type |
| ---- | ---- |
| [aws_cloudwatch_metric_alarm.bucket_object_count](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_metric_alarm) | resource |
| [aws_cloudwatch_metric_alarm.bucket_size_bytes](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_metric_alarm) | resource |
| [aws_s3_bucket_policy.secure_transport](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_policy) | resource |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| <a name="input_attach_deny_insecure_transport_policy"></a> [attach\_deny\_insecure\_transport\_policy](#input\_attach\_deny\_insecure\_transport\_policy) | Deny all S3 actions when aws:SecureTransport is false. | `bool` | `true` | no |
| <a name="input_bucket_name"></a> [bucket\_name](#input\_bucket\_name) | n/a | `string` | n/a | yes |
| <a name="input_bucket_size_alarm_name"></a> [bucket\_size\_alarm\_name](#input\_bucket\_size\_alarm\_name) | n/a | `string` | `null` | no |
| <a name="input_bucket_size_alarm_period_seconds"></a> [bucket\_size\_alarm\_period\_seconds](#input\_bucket\_size\_alarm\_period\_seconds) | n/a | `number` | `86400` | no |
| <a name="input_bucket_size_bytes_threshold"></a> [bucket\_size\_bytes\_threshold](#input\_bucket\_size\_bytes\_threshold) | Default 1 TiB — tune per environment. | `number` | `1099511627776` | no |
| <a name="input_create_bucket_size_alarm"></a> [create\_bucket\_size\_alarm](#input\_create\_bucket\_size\_alarm) | n/a | `bool` | `true` | no |
| <a name="input_create_object_count_alarm"></a> [create\_object\_count\_alarm](#input\_create\_object\_count\_alarm) | n/a | `bool` | `true` | no |
| <a name="input_kms_deletion_window_in_days"></a> [kms\_deletion\_window\_in\_days](#input\_kms\_deletion\_window\_in\_days) | n/a | `number` | `7` | no |
| <a name="input_kms_description"></a> [kms\_description](#input\_kms\_description) | n/a | `string` | `"KMS key for S3 bucket encryption"` | no |
| <a name="input_lifecycle_rules"></a> [lifecycle\_rules](#input\_lifecycle\_rules) | Passed through to terraform-aws-modules/s3-bucket `lifecycle_rule`. Empty disables lifecycle. | `any` | `[]` | no |
| <a name="input_object_count_alarm_name"></a> [object\_count\_alarm\_name](#input\_object\_count\_alarm\_name) | n/a | `string` | `null` | no |
| <a name="input_object_count_alarm_period_seconds"></a> [object\_count\_alarm\_period\_seconds](#input\_object\_count\_alarm\_period\_seconds) | n/a | `number` | `86400` | no |
| <a name="input_object_count_threshold"></a> [object\_count\_threshold](#input\_object\_count\_threshold) | Alarm when StandardStorage object count exceeds this value. | `number` | `1000000` | no |
| <a name="input_tags"></a> [tags](#input\_tags) | n/a | `map(string)` | `{}` | no |

## Outputs

| Name | Description |
| ---- | ----------- |
| <a name="output_kms_key_arn"></a> [kms\_key\_arn](#output\_kms\_key\_arn) | n/a |
| <a name="output_kms_key_id"></a> [kms\_key\_id](#output\_kms\_key\_id) | n/a |
| <a name="output_s3_bucket_arn"></a> [s3\_bucket\_arn](#output\_s3\_bucket\_arn) | n/a |
| <a name="output_s3_bucket_id"></a> [s3\_bucket\_id](#output\_s3\_bucket\_id) | n/a |
<!-- END_TF_DOCS -->
