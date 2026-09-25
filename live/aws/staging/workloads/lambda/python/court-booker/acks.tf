# Friend ACK window with auto-cancel. After a booking, friends on the court's
# roster get personal links; without quorum by the deadline the reservation is
# cancelled (enforce) or the owner is told it would have been (notify_only).
# Every resource here is gated on local.ack_enabled (ack_mode != "off" and a
# stable zip), so ack_mode = "off" leaves the deployed stack unchanged.

locals {
  ack_functions = local.ack_enabled ? {
    workflow = { timeout = 300, handler = "booker.ack_workflow.lambda_handler" }
    api      = { timeout = 15, handler = "booker.ack_api.lambda_handler" }
  } : {}

  ack_routes = local.ack_enabled ? toset(["GET", "POST"]) : toset([])

  # Retry only Lambda service faults. Handler errors are never retried here, so a
  # failing send_invites cannot loop and resend invites.
  ack_lambda_retry = [
    {
      ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"]
      IntervalSeconds = 2
      MaxAttempts     = 3
      BackoffRate     = 2
    }
  ]

  ack_leading_keys = ["BOOKING#*", "TOKEN#*"]
}

resource "aws_dynamodb_table" "acks" {
  # checkov:skip=CKV_AWS_119:AWS-owned encryption protects short-lived ack records without a dedicated CMK.
  count                       = local.ack_enabled ? 1 : 0
  name                        = "court-booker-api-acks"
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
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
}

resource "aws_ssm_parameter" "ack_roster" {
  # checkov:skip=CKV_AWS_337:AWS-managed alias/aws/ssm encrypts a standard SecureString without a $1/month CMK.
  count       = local.ack_enabled ? 1 : 0
  name        = "/staging/court-booker-api/ack-roster"
  description = "Friend ACK roster JSON (activity to list of name and email). Put with scripts/court-booker-put-roster.sh, never tfvars."
  type        = "SecureString"
  tier        = "Standard"
  key_id      = "alias/aws/ssm"
  value       = "UNSET"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_cloudwatch_log_group" "ack" {
  # checkov:skip=CKV_AWS_158:Default encryption suffices for sanitized ack logs that never include tokens.
  # checkov:skip=CKV_AWS_338:14 days matches the booker log group.
  for_each          = local.ack_functions
  name              = "/aws/lambda/court-booker-api-ack-${each.key}"
  retention_in_days = 14
}

resource "aws_iam_role" "ack" {
  for_each           = local.ack_functions
  name               = "court-booker-api-ack-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

data "aws_iam_policy_document" "ack_workflow" {
  count = local.ack_enabled ? 1 : 0

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.ack["workflow"].arn}:*"]
  }

  statement {
    sid = "AckTable"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Query",
      "dynamodb:ConditionCheckItem",
    ]
    resources = [aws_dynamodb_table.acks[0].arn]
    condition {
      test     = "ForAllValues:StringLike"
      variable = "dynamodb:LeadingKeys"
      values   = local.ack_leading_keys
    }
  }

  statement {
    sid       = "Roster"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.ack_roster[0].arn]
  }

  statement {
    sid       = "DecryptSsm"
    actions   = ["kms:Decrypt"]
    resources = [data.aws_kms_alias.ssm.target_key_arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.region}.amazonaws.com"]
    }
  }

  # While the account is in the SES sandbox, SES also authorizes the call against
  # every recipient identity, so the resource must cover identity/* in this
  # account. ses:FromAddress pins the sender to the configured identity.
  statement {
    sid       = "SendInvites"
    actions   = ["ses:SendEmail"]
    resources = ["arn:aws:ses:${var.region}:${var.aws_account_id}:identity/*"]
    condition {
      test     = "StringEquals"
      variable = "ses:FromAddress"
      values   = [local.ack_sender_email]
    }
  }

  # A retried AwaitAcks task carries a fresh task token; send_invites completes it
  # at once if quorum was already reached. SendTaskSuccess has no resource type.
  statement {
    sid       = "CompleteAckWindow"
    actions   = ["states:SendTaskSuccess"]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "ack_api" {
  count = local.ack_enabled ? 1 : 0

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.ack["api"].arn}:*"]
  }

  statement {
    sid = "AckTable"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:UpdateItem",
      "dynamodb:ConditionCheckItem",
    ]
    resources = [aws_dynamodb_table.acks[0].arn]
    condition {
      test     = "ForAllValues:StringLike"
      variable = "dynamodb:LeadingKeys"
      values   = local.ack_leading_keys
    }
  }

  # SendTaskSuccess has no resource type; task tokens are the authorization.
  statement {
    sid       = "CompleteAckWindow"
    actions   = ["states:SendTaskSuccess"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "ack" {
  # checkov:skip=CKV_AWS_355:states:SendTaskSuccess does not support resource-level permissions and requires Resource '*'.
  # checkov:skip=CKV_AWS_356:states:SendTaskSuccess does not support resource-level permissions and requires Resource '*'.
  for_each = local.ack_functions
  name     = "ack-${each.key}"
  role     = aws_iam_role.ack[each.key].id
  policy   = each.key == "workflow" ? data.aws_iam_policy_document.ack_workflow[0].json : data.aws_iam_policy_document.ack_api[0].json
}

resource "aws_lambda_function" "ack" {
  # checkov:skip=CKV_AWS_117:Public AWS APIs (SES, DynamoDB, Step Functions) need no VPC or NAT gateway.
  # checkov:skip=CKV_AWS_116:Both functions are invoked synchronously (Step Functions, API Gateway); callers own retries.
  # checkov:skip=CKV_AWS_50:CloudWatch metrics and sanitized logs suffice for this personal workflow.
  # checkov:skip=CKV_AWS_173:Environment contains resource identifiers and addresses only, never credentials or tokens.
  # checkov:skip=CKV_AWS_272:Code signing is not used for this versioned personal zip.
  # checkov:skip=CKV_AWS_115:The account's unreserved concurrency floor precludes reservations; API throttling bounds work.
  for_each          = local.ack_functions
  function_name     = "court-booker-api-ack-${each.key}"
  role              = aws_iam_role.ack[each.key].arn
  handler           = each.value.handler
  runtime           = "python3.14"
  architectures     = ["arm64"]
  memory_size       = 256
  timeout           = each.value.timeout
  s3_bucket         = data.aws_s3_bucket.zips.id
  s3_key            = var.booker_api_zip_key
  s3_object_version = data.aws_s3_object.zip[0].version_id
  environment {
    variables = merge({
      ACK_TABLE = aws_dynamodb_table.acks[0].name
      ACK_MODE  = var.ack_mode
      }, each.key == "workflow" ? {
      ACK_ROSTER_PARAMETER = aws_ssm_parameter.ack_roster[0].name
      ACK_SENDER_EMAIL     = local.ack_sender_email
      ACK_BASE_URL         = aws_apigatewayv2_api.calendar.api_endpoint
      OWNER_EMAIL          = var.alert_email
      BOOKINGS_PATH        = "/var/task/bookings.yaml"
    } : {})
  }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.ack[each.key].name
  }
  depends_on = [aws_iam_role_policy.ack]
}

# --- Ack state machine -------------------------------------------------------

resource "aws_cloudwatch_log_group" "ack_sfn" {
  # checkov:skip=CKV_AWS_158:Default AWS-managed encryption is enough for an ERROR-level state machine log.
  # checkov:skip=CKV_AWS_338:14 days matches the booker log group.
  count             = local.ack_enabled ? 1 : 0
  name              = "/aws/vendedlogs/states/court-booker-api-ack"
  retention_in_days = 14
}

resource "aws_iam_role" "ack_sfn" {
  count              = local.ack_enabled ? 1 : 0
  name               = "court-booker-api-ack-sfn"
  assume_role_policy = data.aws_iam_policy_document.sfn_trust.json
}

data "aws_iam_policy_document" "ack_sfn" {
  statement {
    sid     = "InvokeAckFunctions"
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    resources = [
      "arn:aws:lambda:${var.region}:${var.aws_account_id}:function:court-booker-api",
      "arn:aws:lambda:${var.region}:${var.aws_account_id}:function:court-booker-api-calendar-writer",
      "arn:aws:lambda:${var.region}:${var.aws_account_id}:function:court-booker-api-ack-workflow",
    ]
  }

  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "ack_sfn" {
  # checkov:skip=CKV_AWS_355:Step Functions log delivery APIs require Resource '*'.
  # checkov:skip=CKV_AWS_356:Step Functions log delivery APIs require Resource '*'.
  count  = local.ack_enabled ? 1 : 0
  name   = "court-booker-api-ack-sfn"
  role   = aws_iam_role.ack_sfn[0].id
  policy = data.aws_iam_policy_document.ack_sfn.json
}

resource "aws_sfn_state_machine" "ack" {
  # checkov:skip=CKV_AWS_284:X-Ray is skipped to keep a once-per-booking path cheap.
  # checkov:skip=CKV_AWS_285:ERROR-level CloudWatch logs are enough; execution data would store friends' addresses and task tokens.
  count = local.ack_enabled ? 1 : 0

  name     = "court-booker-api-ack"
  role_arn = aws_iam_role.ack_sfn[0].arn
  type     = "STANDARD"

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.ack_sfn[0].arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }

  # Plain Lambda-ARN tasks return the function's output directly, so $.window,
  # $.expiry and $.cancel hold the handler results without ResultSelector.
  definition = jsonencode({
    Comment        = "Friend ACK window for one booking. Waits on a task token; cancels only in enforce mode and only the expected reservation."
    StartAt        = "Prepare"
    TimeoutSeconds = 259200
    States = {
      Prepare = {
        Type     = "Task"
        Resource = aws_lambda_function.ack["workflow"].arn
        Parameters = {
          action           = "prepare"
          "booking.$"      = "$"
          ack_window_hours = var.ack_window_hours
          ack_required     = var.ack_required
        }
        ResultPath = "$.window"
        Retry      = local.ack_lambda_retry
        Next       = "AwaitAcks"
      }
      AwaitAcks = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke.waitForTaskToken"
        Parameters = {
          FunctionName = aws_lambda_function.ack["workflow"].arn
          Payload = {
            action             = "send_invites"
            "reservation_id.$" = "$.window.reservation_id"
            "task_token.$"     = "$$.Task.Token"
          }
        }
        TimeoutSecondsPath = "$.window.timeout_seconds"
        ResultPath         = "$.ack"
        # Service faults only; see local.ack_lambda_retry. No States.ALL retry.
        Retry = local.ack_lambda_retry
        Catch = [
          { ErrorEquals = ["States.Timeout"], ResultPath = null, Next = "Expire" },
          { ErrorEquals = ["States.ALL"], ResultPath = "$.ack_error", Next = "AckFailed" }
        ]
        Next = "NotifyConfirmed"
      }
      Expire = {
        Type     = "Task"
        Resource = aws_lambda_function.ack["workflow"].arn
        Parameters = {
          action             = "expire"
          "reservation_id.$" = "$.window.reservation_id"
        }
        ResultPath = "$.expiry"
        Retry      = local.ack_lambda_retry
        Next       = "ExpiryOutcome"
      }
      ExpiryOutcome = {
        Type = "Choice"
        Choices = [
          { Variable = "$.expiry.expired", BooleanEquals = false, Next = "NotifyConfirmed" },
          { Variable = "$.expiry.cancel", BooleanEquals = true, Next = "CancelBooking" }
        ]
        Default = "NotifyExpiredNotifyOnly"
      }
      CancelBooking = {
        Type       = "Task"
        Resource   = aws_lambda_function.booker[0].arn
        InputPath  = "$.expiry.cancel_event"
        ResultPath = "$.cancel"
        Retry      = [{ ErrorEquals = ["States.ALL"], IntervalSeconds = 30, MaxAttempts = 3, BackoffRate = 2 }]
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.cancel_error", Next = "NotifyCancelFailed" }]
        Next       = "CancelOutcome"
      }
      CancelOutcome = {
        Type = "Choice"
        Choices = [
          { Variable = "$.cancel.status", StringEquals = "cancelled", Next = "PublishCalendarCancelled" }
        ]
        Default = "NotifyCancelled"
      }
      PublishCalendarCancelled = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.calendar["writer"].arn
          "Payload.$"  = "$.cancel"
        }
        ResultPath = null
        Retry      = [{ ErrorEquals = ["States.ALL"], IntervalSeconds = 2, MaxAttempts = 2, BackoffRate = 2 }]
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = null, Next = "NotifyCancelled" }]
        Next       = "NotifyCancelled"
      }
      NotifyConfirmed = {
        Type       = "Task"
        Resource   = aws_lambda_function.ack["workflow"].arn
        Parameters = { action = "notify", kind = "confirmed", "reservation_id.$" = "$.window.reservation_id" }
        ResultPath = null
        Retry      = local.ack_lambda_retry
        Next       = "Done"
      }
      NotifyCancelled = {
        Type       = "Task"
        Resource   = aws_lambda_function.ack["workflow"].arn
        Parameters = { action = "notify", kind = "cancelled", "reservation_id.$" = "$.window.reservation_id" }
        ResultPath = null
        Retry      = local.ack_lambda_retry
        Next       = "Done"
      }
      NotifyExpiredNotifyOnly = {
        Type       = "Task"
        Resource   = aws_lambda_function.ack["workflow"].arn
        Parameters = { action = "notify", kind = "expired_notify_only", "reservation_id.$" = "$.window.reservation_id" }
        ResultPath = null
        Retry      = local.ack_lambda_retry
        Next       = "Done"
      }
      NotifyCancelFailed = {
        Type       = "Task"
        Resource   = aws_lambda_function.ack["workflow"].arn
        Parameters = { action = "notify", kind = "cancel_failed", "reservation_id.$" = "$.window.reservation_id" }
        ResultPath = null
        Retry      = local.ack_lambda_retry
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = null, Next = "AutoCancelFailed" }]
        Next       = "AutoCancelFailed"
      }
      AutoCancelFailed = {
        Type  = "Fail"
        Error = "AutoCancelFailed"
        Cause = "ack quorum missed and cancellation failed; the court may still be booked"
      }
      AckFailed = {
        Type  = "Fail"
        Error = "AckWorkflowFailed"
        Cause = "ack window failed; booking kept"
      }
      Done = { Type = "Succeed" }
    }
  })

  depends_on = [aws_iam_role_policy.ack_sfn]
}

# --- Friend-facing links on the existing calendar HTTP API --------------------

resource "aws_apigatewayv2_integration" "ack" {
  count                  = local.ack_enabled ? 1 : 0
  api_id                 = aws_apigatewayv2_api.calendar.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.ack["api"].invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 15000
}

resource "aws_apigatewayv2_route" "ack" {
  # checkov:skip=CKV_AWS_309:Friends authenticate with single-purpose opaque path tokens whose hashes are validated by the handler.
  for_each  = local.ack_routes
  api_id    = aws_apigatewayv2_api.calendar.id
  route_key = "${each.key} /acks/{token}"
  target    = "integrations/${aws_apigatewayv2_integration.ack[0].id}"
}

resource "aws_lambda_permission" "ack_gateway" {
  for_each      = local.ack_routes
  statement_id  = "AllowAckGateway${title(lower(each.key))}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ack["api"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.calendar.execution_arn}/*/${each.key}/acks/*"
}

# --- Alarms --------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "ack_failed" {
  count               = local.ack_enabled ? 1 : 0
  alarm_name          = "court-booker-api-ack-failed"
  alarm_description   = "ACK / auto-cancel workflow failed. The court may still be booked; cancel manually if nobody confirmed."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.ack[0].arn }
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "ack_timed_out" {
  count               = local.ack_enabled ? 1 : 0
  alarm_name          = "court-booker-api-ack-timed-out"
  alarm_description   = "ACK / auto-cancel workflow exceeded its 72-hour limit. The court may still be booked; cancel manually if nobody confirmed."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsTimedOut"
  namespace           = "AWS/States"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.ack[0].arn }
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "ack_api_errors" {
  count               = local.ack_enabled ? 1 : 0
  alarm_name          = "court-booker-api-ack-api-errors"
  alarm_description   = "ACK link handler raised an error; a friend's accept or decline may not have been recorded."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions          = { FunctionName = aws_lambda_function.ack["api"].function_name }
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
