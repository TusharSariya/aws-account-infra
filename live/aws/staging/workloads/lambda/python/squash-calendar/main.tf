module "calendar" {
  source                       = "../../../../../../../modules/aws/swimming-calendar"
  app_root                     = abspath("${path.module}/../../../../../../..")
  zip_bucket_name              = local.zip_bucket_name
  aws_account_id               = var.aws_account_id
  region                       = var.region
  service_name                 = "squash-calendar"
  calendar_source              = "squash"
  route                        = "/calendars/squash.ics"
  calendar_name                = "Tushar ASC Squash"
  uid_domain                   = "squash-calendar"
  package_builder              = "scripts/squash-package.py"
  handlers                     = { sync = "squash_calendar.handlers.sync", feed = "squash_calendar.handlers.feed" }
  refresh_schedule             = "cron(15 3 * * ? *)"
  additional_refresh_schedules = { prematch = "cron(30 16 ? * TUE *)" }
  memory_sizes                 = { sync = 512, feed = 256 }
}

resource "aws_cloudwatch_metric_alarm" "enrichment" {
  alarm_name          = "squash-calendar-enrichment-failure"
  alarm_description   = "Club Locker enrichment failed; PDF fixtures remain available"
  namespace           = "SquashCalendar"
  metric_name         = "EnrichmentFailure"
  dimensions          = { Service = "squash-calendar" }
  period              = 300
  evaluation_periods  = 1
  statistic           = "Maximum"
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [module.calendar.background_worker.alerts_topic]
}
output "calendar_url" { value = module.calendar.calendar_url }
output "sync_function" { value = module.calendar.sync_function }
