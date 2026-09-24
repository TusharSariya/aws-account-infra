module "calendar" {
  source                   = "../../../../../../../modules/aws/swimming-calendar"
  app_root                 = abspath("${path.module}/../../../../../../..")
  zip_bucket_name          = local.zip_bucket_name
  aws_account_id           = var.aws_account_id
  region                   = var.region
  service_name             = "iracing-calendar"
  calendar_source          = "iracing"
  calendar_name            = "iRacing irregular races"
  uid_domain               = "iracing-calendar"
  package_builder          = "scripts/iracing-package.py"
  handlers                 = { sync = "iracing_calendar.sync.lambda_handler", feed = "iracing_calendar.feed.lambda_handler" }
  route                    = "/calendars/iracing.ics"
  refresh_schedule         = "cron(0 3 ? * TUE *)"
  refresh_name_suffix      = "weekly"
  health_threshold_seconds = 691200
  sync_object_keys         = ["current.json", "source-cache.json"]
  memory_sizes             = { sync = 1024, feed = 256 }
  sync_timeout             = 540
}
output "calendar_url" { value = module.calendar.calendar_url }
output "sync_function" { value = module.calendar.sync_function }
