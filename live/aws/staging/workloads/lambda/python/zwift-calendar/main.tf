locals {
  credentials_parameter = "/staging/zwift-calendar/credentials"
  tokens_parameter      = "/staging/zwift-calendar/tokens"
}

module "calendar" {
  source                   = "../../../../../../../modules/aws/swimming-calendar"
  app_root                 = abspath("${path.module}/../../../../../../..")
  zip_bucket_name          = local.zip_bucket_name
  aws_account_id           = var.aws_account_id
  region                   = var.region
  service_name             = "zwift-calendar"
  calendar_source          = "zwift"
  calendar_name            = "Zwift races and special events"
  uid_domain               = "zwift-calendar"
  package_builder          = "scripts/zwift-package.py"
  handlers                 = { sync = "zwift_calendar.service.sync_handler", feed = "zwift_calendar.service.feed_handler" }
  route                    = "/calendars/zwift-banded.ics"
  additional_routes        = ["/calendars/zwift-unbanded.ics"]
  refresh_schedule         = "cron(0 * * * ? *)"
  refresh_timezone         = "UTC"
  refresh_name_suffix      = "hourly"
  schedule_enabled         = var.schedule_enabled
  health_threshold_seconds = 10800
  sync_object_keys         = ["current.json", "private.json", "power-state.json", "history/state.json", "history/targets.json"]
  feed_object_keys         = ["current.json", "history/state.json", "history/targets.json"]
  memory_sizes             = { sync = 512, feed = 256 }
  sync_timeout             = 540
  sync_parameter_reads     = [local.credentials_parameter, local.tokens_parameter]
  sync_parameter_writes    = [local.tokens_parameter]
  function_environment = {
    feed = { HISTORY_ENABLED = tostring(var.history_enabled) }
    sync = {
      ZWIFT_CREDENTIALS_PARAMETER = local.credentials_parameter
      ZWIFT_TOKENS_PARAMETER      = local.tokens_parameter
      ZWIFT_MEASURED_MARGIN       = tostring(var.measured_planning_margin)
      ZWIFT_WIDE_MARGIN           = tostring(var.wide_planning_margin)
      ZWIFT_DEFAULT_POWER_CURVE   = jsonencode(var.default_power_curve)
    }
  }
}

output "banded_calendar_url" { value = module.calendar.calendar_urls["/calendars/zwift-banded.ics"] }
output "unbanded_calendar_url" { value = module.calendar.calendar_urls["/calendars/zwift-unbanded.ics"] }
output "sync_function" { value = module.calendar.sync_function }
output "credentials_parameter" { value = local.credentials_parameter }
