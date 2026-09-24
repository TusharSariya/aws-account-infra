# Reuse the existing SES-backed alarm mailer and verified recipient.
data "aws_sns_topic" "alerts" { name = "court-booker-api-alerts" }
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each            = local.functions
  alarm_name          = "technology-digest-${each.key}-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 3600
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions          = { FunctionName = aws_lambda_function.digest[each.key].function_name }
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}
resource "aws_cloudwatch_metric_alarm" "failures" {
  alarm_name          = "technology-digest-failure-queue"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions          = { QueueName = aws_sqs_queue.failures.name }
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}
resource "aws_cloudwatch_metric_alarm" "health" {
  for_each            = toset(["CollectionFailures", "AmbiguousSend", "MissedDelivery", "StaleSources"])
  alarm_name          = "technology-digest-${each.key}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = each.key
  namespace           = "TechnologyDigest"
  period              = 3600
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions          = { Scope = "all" }
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}
resource "aws_cloudwatch_metric_alarm" "collector_missing" {
  count               = var.schedules_enabled ? 1 : 0
  alarm_name          = "technology-digest-collector-missing"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  metric_name         = "Invocations"
  namespace           = "AWS/Lambda"
  period              = 3600
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "breaching"
  dimensions          = { FunctionName = aws_lambda_function.digest["collector"].function_name }
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}

resource "aws_ses_configuration_set" "digest" {
  name = "technology-digest"
  delivery_options { tls_policy = "Require" }
}
resource "aws_ses_event_destination" "digest" {
  name                   = "delivery-health"
  configuration_set_name = aws_ses_configuration_set.digest.name
  enabled                = true
  matching_types         = ["send", "delivery", "bounce", "complaint", "reject"]
  cloudwatch_destination {
    default_value  = "technology-digest"
    dimension_name = "workload"
    value_source   = "messageTag"
  }
}
resource "aws_cloudwatch_metric_alarm" "ses" {
  for_each            = toset(["Bounce", "Complaint", "Reject"])
  alarm_name          = "technology-digest-ses-${each.key}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = each.key
  namespace           = "AWS/SES"
  period              = 3600
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions          = { workload = "technology-digest" }
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}
