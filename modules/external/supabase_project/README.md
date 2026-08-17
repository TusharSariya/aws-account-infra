# Supabase project

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
| ---- | ------- |
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | >= 1.8 |
| <a name="requirement_supabase"></a> [supabase](#requirement\_supabase) | = 1.9.1 |

## Providers

| Name | Version |
| ---- | ------- |
| <a name="provider_supabase"></a> [supabase](#provider\_supabase) | = 1.9.1 |

## Resources

| Name | Type |
| ---- | ---- |
| [supabase_project.this](https://registry.terraform.io/providers/supabase/supabase/1.9.1/docs/resources/project) | resource |
| [supabase_settings.this](https://registry.terraform.io/providers/supabase/supabase/1.9.1/docs/resources/settings) | resource |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| <a name="input_database_password"></a> [database\_password](#input\_database\_password) | n/a | `string` | n/a | yes |
| <a name="input_organization_id"></a> [organization\_id](#input\_organization\_id) | n/a | `string` | n/a | yes |
| <a name="input_project_name"></a> [project\_name](#input\_project\_name) | n/a | `string` | n/a | yes |
| <a name="input_redirect_urls"></a> [redirect\_urls](#input\_redirect\_urls) | n/a | `list(string)` | n/a | yes |
| <a name="input_region"></a> [region](#input\_region) | n/a | `string` | n/a | yes |
| <a name="input_site_url"></a> [site\_url](#input\_site\_url) | n/a | `string` | n/a | yes |

## Outputs

| Name | Description |
| ---- | ----------- |
| <a name="output_project"></a> [project](#output\_project) | n/a |
<!-- END_TF_DOCS -->
