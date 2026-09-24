locals {
  app_root = abspath("${path.module}/../../../../../../..")
  functions = {
    sync = { timeout = 600, concurrency = 1 }
    feed = { timeout = 15, concurrency = 5 }
  }
}

data "external" "package" {
  program = ["python3", "${local.app_root}/scripts/swim-package.py"]
  query   = { root = local.app_root }
}

resource "aws_s3_object" "release" {
  bucket      = local.zip_bucket_name
  key         = "stable/swim-calendar/${data.external.package.result.sha256}.zip"
  source      = data.external.package.result.path
  source_hash = data.external.package.result.sha256
}

resource "aws_s3_bucket" "snapshot" {
  # checkov:skip=CKV_AWS_18:Access is limited to two service roles; API access logs cover downloads.
  # checkov:skip=CKV_AWS_144:A public schedule can be regenerated; regional replication is unnecessary.
  # checkov:skip=CKV_AWS_145:AWS-owned encryption suffices for public schedule snapshots.
  # checkov:skip=CKV2_AWS_62:There are no object-triggered consumers; scheduled reconciliation owns publication.
  bucket = "swim-calendar-${var.aws_account_id}-${var.region}"
  lifecycle { prevent_destroy = true }
}
resource "aws_s3_bucket_versioning" "snapshot" {
  bucket = aws_s3_bucket.snapshot.id
  versioning_configuration { status = "Enabled" }
}
# Public schedule snapshots use S3 AES256 encryption; no sensitive records require a dedicated CMK.
# trivy:ignore:AVD-AWS-0132
resource "aws_s3_bucket_server_side_encryption_configuration" "snapshot" {
  bucket = aws_s3_bucket.snapshot.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_public_access_block" "snapshot" {
  bucket                  = aws_s3_bucket.snapshot.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_lifecycle_configuration" "snapshot" {
  bucket = aws_s3_bucket.snapshot.id
  rule {
    id     = "old-snapshots"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 35 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
  depends_on = [aws_s3_bucket_versioning.snapshot]
}
data "aws_iam_policy_document" "bucket" {
  statement {
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.snapshot.arn, "${aws_s3_bucket.snapshot.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}
resource "aws_s3_bucket_policy" "snapshot" {
  bucket = aws_s3_bucket.snapshot.id
  policy = data.aws_iam_policy_document.bucket.json
}

resource "aws_sqs_queue" "failures" {
  name                      = "swim-calendar-failures"
  sqs_managed_sse_enabled   = true
  message_retention_seconds = 1209600
}
data "aws_sns_topic" "alerts" { name = "court-booker-api-alerts" }

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}
resource "aws_cloudwatch_log_group" "lambda" {
  # checkov:skip=CKV_AWS_158:AWS-owned encryption suffices for sanitized public-schedule logs.
  # checkov:skip=CKV_AWS_338:14-day operational retention matches existing calendar services.
  for_each          = local.functions
  name              = "/aws/lambda/swim-calendar-${each.key}"
  retention_in_days = 14
}
resource "aws_iam_role" "lambda" {
  for_each           = local.functions
  name               = "swim-calendar-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}
data "aws_iam_policy_document" "lambda" {
  for_each = local.functions
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda[each.key].arn}:*"]
  }
  statement {
    actions   = each.key == "sync" ? ["s3:GetObject", "s3:PutObject"] : ["s3:GetObject"]
    resources = ["${aws_s3_bucket.snapshot.arn}/current.json"]
  }
  # Allows the SDK to distinguish an uninitialized snapshot (404) from access denied.
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.snapshot.arn]

  }
  dynamic "statement" {
    for_each = each.key == "sync" ? [1] : []
    content {
      actions   = ["sqs:SendMessage"]
      resources = [aws_sqs_queue.failures.arn]
    }
  }
}
resource "aws_iam_role_policy" "lambda" {
  for_each = local.functions
  role     = aws_iam_role.lambda[each.key].id
  policy   = data.aws_iam_policy_document.lambda[each.key].json
}
resource "aws_lambda_function" "app" {
  # checkov:skip=CKV_AWS_117:Public Upace and S3 access require no VPC or NAT gateway.
  # checkov:skip=CKV_AWS_116:Sync has an async failure destination; synchronous feed errors have alarms.
  # checkov:skip=CKV_AWS_50:CloudWatch metrics and logs cover this small public feed.
  # checkov:skip=CKV_AWS_173:Environment contains only a bucket name, no secrets.
  # checkov:skip=CKV_AWS_272:Content-addressed locked builds are reviewed through IaC; signing is not configured.
  for_each      = local.functions
  function_name = "swim-calendar-${each.key}"
  role          = aws_iam_role.lambda[each.key].arn
  # AWS supports Python 3.14; the pinned static AWS ruleset predates this runtime.
  # tflint-ignore: aws_lambda_function_invalid_runtime
  runtime                        = "python3.14"
  architectures                  = ["arm64"]
  handler                        = "swim_calendar.handlers.${each.key}"
  s3_bucket                      = aws_s3_object.release.bucket
  s3_key                         = aws_s3_object.release.key
  source_code_hash               = data.external.package.result.base64sha256
  memory_size                    = 256
  timeout                        = each.value.timeout
  reserved_concurrent_executions = each.value.concurrency
  environment {
    variables = { SNAPSHOT_BUCKET = aws_s3_bucket.snapshot.id }
  }
  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy.lambda]
}
resource "aws_lambda_function_event_invoke_config" "sync" {
  function_name                = aws_lambda_function.app["sync"].function_name
  maximum_event_age_in_seconds = 3600
  maximum_retry_attempts       = 2
  destination_config {
    on_failure {
      destination = aws_sqs_queue.failures.arn
    }
  }
}

data "aws_iam_policy_document" "scheduler_trust" {
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
  }
}
resource "aws_iam_role" "scheduler" {
  name               = "swim-calendar-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
}
resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [for f in aws_lambda_function.app : f.arn] },
    { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = aws_sqs_queue.failures.arn }
  ] })
}
resource "aws_scheduler_schedule" "refresh" {
  # checkov:skip=CKV_AWS_297:Schedule payloads contain no secrets; AWS-owned encryption is sufficient.
  name                         = "swim-calendar-daily"
  schedule_expression          = "cron(0 3 * * ? *)"
  schedule_expression_timezone = "America/St_Johns"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_lambda_function.app["sync"].arn
    role_arn = aws_iam_role.scheduler.arn
    input    = "{}"
    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 2
    }
    dead_letter_config { arn = aws_sqs_queue.failures.arn }
  }
}
resource "aws_scheduler_schedule" "health" {
  # checkov:skip=CKV_AWS_297:Schedule payloads contain no secrets; AWS-owned encryption is sufficient.
  name                = "swim-calendar-health"
  schedule_expression = "rate(1 hour)"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_lambda_function.app["feed"].arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ health = true })
    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 2
    }
    dead_letter_config { arn = aws_sqs_queue.failures.arn }
  }
}

resource "aws_apigatewayv2_api" "feed" {
  name          = "swim-calendar"
  protocol_type = "HTTP"
}
resource "aws_apigatewayv2_integration" "feed" {
  api_id                 = aws_apigatewayv2_api.feed.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.app["feed"].invoke_arn
  payload_format_version = "2.0"
}
resource "aws_apigatewayv2_route" "feed" {
  # checkov:skip=CKV_AWS_309:This route intentionally publishes public YMCA schedules without authentication.
  api_id    = aws_apigatewayv2_api.feed.id
  route_key = "GET /calendars/swimming.ics"
  target    = "integrations/${aws_apigatewayv2_integration.feed.id}"
}
resource "aws_cloudwatch_log_group" "api" {
  # checkov:skip=CKV_AWS_158:Only request IDs, status and latency are logged.
  # checkov:skip=CKV_AWS_338:14 days matches the service's operational retention.
  name              = "/aws/apigateway/swim-calendar"
  retention_in_days = 14
}
resource "aws_apigatewayv2_stage" "feed" {
  api_id      = aws_apigatewayv2_api.feed.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit   = 10
    throttling_rate_limit    = 5
    detailed_metrics_enabled = true
  }
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format          = jsonencode({ requestId = "$context.requestId", status = "$context.status", latency = "$context.responseLatency" })
  }
}
resource "aws_lambda_permission" "api" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.app["feed"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.feed.execution_arn}/*/GET/calendars/swimming.ics"
}
resource "aws_cloudwatch_metric_alarm" "errors" {
  for_each            = local.functions
  alarm_name          = "swim-calendar-${each.key}-errors"
  alarm_description   = each.key == "feed" ? "Feed failure or hourly check found snapshot older than 36 hours" : "Daily swimming refresh failed; previous snapshot retained"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.app[each.key].function_name }
  period              = 300
  evaluation_periods  = 1
  statistic           = "Sum"
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}
resource "aws_cloudwatch_metric_alarm" "delivery" {
  alarm_name          = "swim-calendar-failed-delivery"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.failures.name }
  period              = 300
  evaluation_periods  = 1
  statistic           = "Maximum"
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.alerts.arn]
}
output "calendar_url" { value = "${aws_apigatewayv2_api.feed.api_endpoint}/calendars/swimming.ics" }
output "sync_function" { value = aws_lambda_function.app["sync"].function_name }
