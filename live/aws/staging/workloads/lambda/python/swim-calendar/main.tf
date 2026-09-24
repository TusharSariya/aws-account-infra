module "calendar" {
  source          = "../../../../../../../modules/aws/swimming-calendar"
  app_root        = abspath("${path.module}/../../../../../../..")
  zip_bucket_name = local.zip_bucket_name
  aws_account_id  = var.aws_account_id
  region          = var.region
  service_name    = "swim-calendar"
  calendar_source = "ymca"
  calendar_name   = "Ches Penney Swimming"
  uid_domain      = "ymca-swim-calendar"
}
output "calendar_url" { value = module.calendar.calendar_url }
output "sync_function" { value = module.calendar.sync_function }
