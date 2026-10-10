locals {
  history_name = "zwift-calendar-history"
  history      = module.calendar.background_worker
}

data "aws_iam_policy_document" "history_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}
resource "aws_iam_role" "history" {
  name               = local.history_name
  assume_role_policy = data.aws_iam_policy_document.history_trust.json
}
resource "aws_cloudwatch_log_group" "history" {
  # checkov:skip=CKV_AWS_158:Sanitized aggregate counts use AWS-owned encryption.
  # checkov:skip=CKV_AWS_338:Seven days bounds cost for this small batch worker.
  name              = "/aws/lambda/${local.history_name}"
  retention_in_days = 7
}
resource "aws_iam_role_policy" "history" {
  role = aws_iam_role.history.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.history.arn}:*" },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = [for key in ["current.json", "private.json", "history/targets.json", "history/state.json"] : "${local.history.snapshot_arn}/${key}"] },
    { Effect = "Allow", Action = ["s3:PutObject"], Resource = [for key in ["current.json", "history/state.json"] : "${local.history.snapshot_arn}/${key}"] },
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = local.history.snapshot_arn },
    { Effect = "Allow", Action = ["ssm:GetParameter"], Resource = [for name in [local.credentials_parameter, local.tokens_parameter] : "arn:aws:ssm:${var.region}:${var.aws_account_id}:parameter${name}"] },
    { Effect = "Allow", Action = ["ssm:PutParameter"], Resource = "arn:aws:ssm:${var.region}:${var.aws_account_id}:parameter${local.tokens_parameter}" },
    { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = local.history.failure_queue }
  ] })
}
resource "aws_lambda_function" "history" {
  # checkov:skip=CKV_AWS_115:Account quota is 10 with minimum 10 unreserved; the shared S3 lease serializes work and durable admission counters bound runs.
  # checkov:skip=CKV_AWS_117:Public upstream and S3 need no VPC or NAT gateway.
  # checkov:skip=CKV_AWS_116:An asynchronous failure destination is configured separately.
  # checkov:skip=CKV_AWS_50:Native metrics and sanitized summaries cover this bounded worker.
  # checkov:skip=CKV_AWS_173:Environment holds parameter names only, never credentials.
  # checkov:skip=CKV_AWS_272:Content-addressed locked builds are reviewed through IaC.
  function_name = local.history_name
  role          = aws_iam_role.history.arn
  # tflint-ignore: aws_lambda_function_invalid_runtime
  runtime          = "python3.14"
  architectures    = ["arm64"]
  handler          = "zwift_calendar.backfill.handler"
  s3_bucket        = local.history.artifact_bucket
  s3_key           = local.history.artifact_key
  source_code_hash = local.history.artifact_hash
  memory_size      = 512
  timeout          = 180
  environment {
    variables = {
      SNAPSHOT_BUCKET             = local.history.snapshot_bucket
      ZWIFT_CREDENTIALS_PARAMETER = local.credentials_parameter
      ZWIFT_TOKENS_PARAMETER      = local.tokens_parameter
    }
  }
  depends_on = [aws_iam_role_policy.history, aws_cloudwatch_log_group.history]
}
resource "aws_lambda_function_event_invoke_config" "history" {
  function_name                = aws_lambda_function.history.function_name
  maximum_event_age_in_seconds = 60
  maximum_retry_attempts       = 0
  destination_config {
    on_failure { destination = local.history.failure_queue }
  }
}
data "aws_iam_policy_document" "history_schedule_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:scheduler:${var.region}:${var.aws_account_id}:schedule-group/default"]
    }
  }
}
resource "aws_iam_role" "history_schedule" {
  name               = "${local.history_name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.history_schedule_trust.json
}
resource "aws_iam_role_policy" "history_schedule" {
  role = aws_iam_role.history_schedule.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = aws_lambda_function.history.arn },
    { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = local.history.failure_queue }
  ] })
}
resource "aws_scheduler_schedule" "history" {
  # checkov:skip=CKV_AWS_297:Empty payload contains no sensitive information.
  name                         = local.history_name
  state                        = var.history_enabled ? "ENABLED" : "DISABLED"
  schedule_expression          = "cron(20 0/3 * * ? *)"
  schedule_expression_timezone = "UTC"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_lambda_function.history.arn
    role_arn = aws_iam_role.history_schedule.arn
    input    = "{}"
    retry_policy {
      maximum_event_age_in_seconds = 60
      maximum_retry_attempts       = 0
    }
    dead_letter_config { arn = local.history.failure_queue }
  }
}
resource "aws_cloudwatch_metric_alarm" "history_errors" {
  alarm_name          = "${local.history_name}-errors"
  alarm_description   = "Historical backfill failed; published calendars remain available"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.history.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.history.alerts_topic]
}
output "history_function" { value = aws_lambda_function.history.function_name }
