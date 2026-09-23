resource "aws_sns_topic" "alerts" {
  # checkov:skip=CKV_AWS_26:AWS-managed SNS encryption cannot receive CloudWatch alarm publishes; a dedicated CMK would add a monthly KMS charge for weekly alarm JSON.
  name = "court-booker-api-alerts"
}

data "aws_iam_policy_document" "alerts_topic" {
  statement {
    sid    = "AllowCloudWatch"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }
  }
}

resource "aws_sns_topic_policy" "alerts" {
  arn    = aws_sns_topic.alerts.arn
  policy = data.aws_iam_policy_document.alerts_topic.json
}

data "archive_file" "alerter" {
  type        = "zip"
  source_file = "${path.module}/alerter.py"
  output_path = "${path.module}/.terraform/alerter.zip"
}

resource "aws_cloudwatch_log_group" "alerter" {
  # checkov:skip=CKV_AWS_158:Default AWS-managed encryption is enough for alarm-mailer logs.
  # checkov:skip=CKV_AWS_338:14 days matches the booker log group.
  name              = "/aws/lambda/court-booker-api-alerter"
  retention_in_days = 14
}

data "aws_iam_policy_document" "alerter_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "alerter" {
  name               = "court-booker-api-alerter"
  assume_role_policy = data.aws_iam_policy_document.alerter_trust.json
}

data "aws_iam_policy_document" "alerter" {
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.alerter.arn}:*"]
  }

  statement {
    sid    = "SesSend"
    effect = "Allow"
    actions = [
      "ses:SendEmail",
      "ses:SendRawEmail",
    ]
    resources = [data.aws_ses_email_identity.alerts.arn]
  }

  statement {
    sid    = "ReadFailedRun"
    effect = "Allow"
    actions = [
      "states:ListExecutions",
      "states:DescribeExecution",
      "states:GetExecutionHistory",
    ]
    resources = [
      "arn:aws:states:${var.region}:${var.aws_account_id}:stateMachine:court-booker-api",
      "arn:aws:states:${var.region}:${var.aws_account_id}:execution:court-booker-api:*",
    ]
  }
}

resource "aws_iam_role_policy" "alerter" {
  name   = "court-booker-api-alerter"
  role   = aws_iam_role.alerter.id
  policy = data.aws_iam_policy_document.alerter.json
}

resource "aws_lambda_function" "alerter" {
  # checkov:skip=CKV_AWS_117:Mailer only calls SES; a VPC would add NAT cost for no benefit.
  # checkov:skip=CKV_AWS_116:A failed mailer retry is not worth a DLQ for a personal weekly alarm.
  # checkov:skip=CKV_AWS_50:X-Ray is skipped to keep a once-a-week alarm path cheap.
  # checkov:skip=CKV_AWS_173:Environment holds only the alert email, not credentials.
  # checkov:skip=CKV_AWS_272:Code signing is not used for this personal zip.
  # checkov:skip=CKV_AWS_115:This account's unreserved concurrency floor is 10; reserving 1 here would block the booker Lambda.
  filename         = data.archive_file.alerter.output_path
  source_code_hash = data.archive_file.alerter.output_base64sha256
  function_name    = "court-booker-api-alerter"
  role             = aws_iam_role.alerter.arn
  handler          = "alerter.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = 30
  memory_size      = 128

  environment {
    variables = {
      ALERT_FROM        = var.alert_email
      ALERT_TO          = var.alert_email
      STATE_MACHINE_ARN = try(aws_sfn_state_machine.booker[0].arn, "")
    }
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.alerter.name
  }

  depends_on = [aws_iam_role_policy.alerter]
}

resource "aws_lambda_permission" "alerter_sns" {
  statement_id  = "AllowSNS"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.alerter.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.alerts.arn
}

resource "aws_sns_topic_subscription" "alerter" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.alerter.arn
}

resource "aws_cloudwatch_metric_alarm" "booker_failed" {
  alarm_name          = "court-booker-api-failed"
  alarm_description   = "Court booker API workflow failed. The execution distinguishes booking and calendar publication failures. Emails ${var.alert_email} via SES."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions = {
    StateMachineArn = "arn:aws:states:${var.region}:${var.aws_account_id}:stateMachine:court-booker-api"
  }
  alarm_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "booker_throttles" {
  alarm_name          = "court-booker-api-throttles"
  alarm_description   = "Court booker API Lambda was throttled. Emails ${var.alert_email} via SES."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = "court-booker-api"
  }
  alarm_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "scheduler_target_errors" {
  alarm_name          = "court-booker-api-scheduler-target-errors"
  alarm_description   = "EventBridge Scheduler failed to invoke court-booker-api. Emails ${var.alert_email} via SES."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  metric_name         = "TargetErrorCount"
  namespace           = "AWS/Scheduler"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions = {
    ScheduleGroup = aws_scheduler_schedule_group.booker.name
  }
  alarm_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "workflow_timeout" {
  alarm_name          = "court-booker-api-timed-out"
  alarm_description   = "Booking workflow timed out; inspect reservations before retrying."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsTimedOut"
  namespace           = "AWS/States"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions          = { StateMachineArn = "arn:aws:states:${var.region}:${var.aws_account_id}:stateMachine:court-booker-api" }
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "calendar_errors" {
  for_each            = local.calendar_functions
  alarm_name          = "court-booker-api-calendar-${each.key}-errors"
  alarm_description   = "Calendar ${each.key} failed; reservations are not modified by calendar operations."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions          = { FunctionName = aws_lambda_function.calendar[each.key].function_name }
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_log_metric_filter" "calendar_refresh" {
  count          = local.zip_ready ? 1 : 0
  name           = "calendar-refresh-invocation-errors"
  pattern        = "\"Calendar refresh invocation failed\""
  log_group_name = aws_cloudwatch_log_group.calendar["feed"].name
  metric_transformation {
    name      = "RefreshInvocationErrors"
    namespace = "CourtBooker/Calendar"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "calendar_refresh" {
  alarm_name          = "court-booker-api-calendar-refresh-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "RefreshInvocationErrors"
  namespace           = "CourtBooker/Calendar"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "calendar_http" {
  alarm_name          = "court-booker-api-calendar-http-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "5xx"
  namespace           = "AWS/ApiGateway"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions          = { ApiId = aws_apigatewayv2_api.calendar.id }
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
