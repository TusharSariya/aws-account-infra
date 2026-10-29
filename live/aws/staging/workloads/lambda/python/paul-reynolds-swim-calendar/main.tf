module "calendar" {
  source           = "../../../../../../../modules/aws/swimming-calendar"
  app_root         = abspath("${path.module}/../../../../../../..")
  zip_bucket_name  = local.zip_bucket_name
  aws_account_id   = var.aws_account_id
  region           = var.region
  service_name     = "paul-reynolds-swim-calendar"
  calendar_source  = "paul_reynolds"
  calendar_name    = "Paul Reynolds Swimming"
  uid_domain       = "paul-reynolds-swim-calendar"
  schedule_enabled = false
}
output "calendar_url" { value = module.calendar.calendar_url }
output "sync_function" { value = module.calendar.sync_function }
