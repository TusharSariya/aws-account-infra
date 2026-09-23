locals {
  calendar_functions = local.zip_ready ? {
    writer    = { timeout = 20, handler = "booker.calendar_writer.lambda_handler" }
    feed      = { timeout = 15, handler = "booker.calendar_feed.lambda_handler" }
    reconcile = { timeout = 120, handler = "booker.calendar_reconcile.lambda_handler" }
  } : {}
}

resource "aws_dynamodb_table" "calendar" {
  # checkov:skip=CKV_AWS_119:AWS-owned encryption protects this personal calendar without a dedicated CMK.
  name                        = "court-booker-api-calendar"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "PK"
  range_key                   = "SK"
  deletion_protection_enabled = true
  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "SK"
    type = "S"
  }
  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
}

resource "aws_cloudwatch_log_group" "calendar" {
  # checkov:skip=CKV_AWS_158:Default encryption suffices for sanitized calendar operational logs.
  # checkov:skip=CKV_AWS_338:14 days is sufficient for this personal calendar.
  for_each          = local.calendar_functions
  name              = "/aws/lambda/court-booker-api-calendar-${each.key}"
  retention_in_days = 14
}

resource "aws_iam_role" "calendar" {
  for_each           = local.calendar_functions
  name               = "court-booker-api-calendar-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

data "aws_iam_policy_document" "calendar" {
  for_each = local.calendar_functions
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.calendar[each.key].arn}:*"]
  }
  statement {
    sid     = "CalendarRead"
    actions = each.key == "writer" ? ["dynamodb:GetItem"] : ["dynamodb:GetItem", "dynamodb:Query"]
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "dynamodb:LeadingKeys"
      values   = each.key == "feed" ? ["CALENDAR", "SUBSCRIPTIONS"] : ["CALENDAR"]
    }
    resources = [aws_dynamodb_table.calendar.arn]
  }
  statement {
    sid       = "CalendarWrite"
    actions   = each.key == "feed" ? ["dynamodb:UpdateItem"] : (each.key == "writer" ? ["dynamodb:PutItem"] : ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:ConditionCheckItem"])
    resources = [aws_dynamodb_table.calendar.arn]
    condition {
      test     = "ForAllValues:StringLike"
      variable = "dynamodb:LeadingKeys"
      values   = ["CALENDAR"]
    }
  }
  dynamic "statement" {
    for_each = each.key == "feed" ? [1] : []
    content {
      sid       = "RequestRefresh"
      actions   = ["lambda:InvokeFunction"]
      resources = ["arn:aws:lambda:${var.region}:${var.aws_account_id}:function:court-booker-api-calendar-reconcile"]
    }
  }
  dynamic "statement" {
    for_each = each.key == "reconcile" ? [1] : []
    content {
      sid       = "Parameter"
      actions   = ["ssm:GetParameter"]
      resources = [aws_ssm_parameter.my_y.arn]
    }
  }
  dynamic "statement" {
    for_each = each.key == "reconcile" ? [1] : []
    content {
      sid       = "DecryptSsm"
      actions   = ["kms:Decrypt"]
      resources = [data.aws_kms_alias.ssm.target_key_arn]
      condition {
        test     = "StringEquals"
        variable = "kms:ViaService"
        values   = ["ssm.${var.region}.amazonaws.com"]
      }
    }
  }
  dynamic "statement" {
    for_each = each.key == "reconcile" ? [1] : []
    content {
      sid       = "ReportFailure"
      actions   = ["lambda:InvokeFunction"]
      resources = ["arn:aws:lambda:${var.region}:${var.aws_account_id}:function:court-booker-api-alerter"]
    }
  }
}

resource "aws_iam_role_policy" "calendar" {
  for_each = local.calendar_functions
  name     = "calendar"
  role     = aws_iam_role.calendar[each.key].id
  policy   = data.aws_iam_policy_document.calendar[each.key].json
}

resource "aws_lambda_function" "calendar" {
  # checkov:skip=CKV_AWS_117:Public Upace and AWS APIs need no VPC or NAT gateway.
  # checkov:skip=CKV_AWS_116:Synchronous writer/feed callers handle errors; reconciliation has an async failure destination.
  # checkov:skip=CKV_AWS_50:CloudWatch metrics and sanitized logs suffice for this personal feed.
  # checkov:skip=CKV_AWS_173:Environment contains resource identifiers only, never credentials or subscription tokens.
  # checkov:skip=CKV_AWS_272:Code signing is not used for this versioned personal zip.
  # checkov:skip=CKV_AWS_115:The account's unreserved concurrency floor precludes reservations; API throttling and a shared lease bound work.
  for_each          = local.calendar_functions
  function_name     = "court-booker-api-calendar-${each.key}"
  role              = aws_iam_role.calendar[each.key].arn
  handler           = each.value.handler
  runtime           = "python3.14"
  architectures     = ["arm64"]
  memory_size       = 256
  timeout           = each.value.timeout
  s3_bucket         = data.aws_s3_bucket.zips.id
  s3_key            = var.booker_api_zip_key
  s3_object_version = data.aws_s3_object.zip[0].version_id
  environment {
    variables = merge({ CALENDAR_TABLE = aws_dynamodb_table.calendar.name },
      each.key == "feed" ? { CALENDAR_RECONCILE_FUNCTION = "court-booker-api-calendar-reconcile" } : {},
      each.key == "reconcile" ? { CREDENTIALS_PARAMETER = aws_ssm_parameter.my_y.name, BOOKINGS_PATH = "/var/task/bookings.yaml" } : {}
    )
  }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.calendar[each.key].name
  }
  depends_on = [aws_iam_role_policy.calendar]
}

resource "aws_lambda_function_event_invoke_config" "calendar_reconcile" {
  count                        = local.zip_ready ? 1 : 0
  function_name                = aws_lambda_function.calendar["reconcile"].function_name
  maximum_event_age_in_seconds = 300
  maximum_retry_attempts       = 1
  destination_config {
    on_failure { destination = aws_lambda_function.alerter.arn }
  }
}

resource "aws_apigatewayv2_api" "calendar" {
  name          = "court-booker-api-calendar"
  protocol_type = "HTTP"
}

resource "aws_cloudwatch_log_group" "calendar_access" {
  # checkov:skip=CKV_AWS_158:Default encryption suffices for request IDs and status codes.
  # checkov:skip=CKV_AWS_338:14 days is sufficient for personal feed access diagnostics.
  name              = "/aws/apigateway/court-booker-api-calendar"
  retention_in_days = 14
}

resource "aws_apigatewayv2_stage" "calendar" {
  # checkov:skip=CKV_AWS_76:HTTP API access logs explicitly omit URLs and subscription tokens.
  api_id      = aws_apigatewayv2_api.calendar.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit   = 10
    throttling_rate_limit    = 5
    detailed_metrics_enabled = true
  }
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.calendar_access.arn
    format          = jsonencode({ requestId = "$context.requestId", status = "$context.status", responseLength = "$context.responseLength" })
  }
}

resource "aws_apigatewayv2_integration" "calendar" {
  count                  = local.zip_ready ? 1 : 0
  api_id                 = aws_apigatewayv2_api.calendar.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.calendar["feed"].invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 20000
}

resource "aws_apigatewayv2_route" "calendar" {
  # checkov:skip=CKV_AWS_309:Calendar clients authenticate with revocable opaque path tokens validated by the handler.
  count     = local.zip_ready ? 1 : 0
  api_id    = aws_apigatewayv2_api.calendar.id
  route_key = "GET /calendars/{token}/bookings.ics"
  target    = "integrations/${aws_apigatewayv2_integration.calendar[0].id}"
}

resource "aws_lambda_permission" "calendar_gateway" {
  count         = local.zip_ready ? 1 : 0
  statement_id  = "AllowCalendarGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.calendar["feed"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.calendar.execution_arn}/*/GET/calendars/*/bookings.ics"
}

output "calendar_base_url" {
  value       = aws_apigatewayv2_api.calendar.api_endpoint
  description = "Subscription CLI base URL. Tokens are only printed at creation."
}
output "calendar_table_name" { value = aws_dynamodb_table.calendar.name }
output "calendar_reconcile_function_name" { value = try(aws_lambda_function.calendar["reconcile"].function_name, null) }
