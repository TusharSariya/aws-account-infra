module "calendar" {
  source          = "../../../../../../../modules/aws/swimming-calendar"
  app_root        = abspath("${path.module}/../../../../../../..")
  zip_bucket_name = local.zip_bucket_name
  aws_account_id  = var.aws_account_id
  region          = var.region
  service_name    = "ymca-yoga-calendar"
  calendar_source = "ymca_yoga"
  route           = "/calendars/yoga.ics"
  calendar_name   = "Ches Penney Yoga"
  uid_domain      = "ymca-yoga-calendar"
}
output "calendar_url" { value = module.calendar.calendar_url }
output "sync_function" { value = module.calendar.sync_function }
