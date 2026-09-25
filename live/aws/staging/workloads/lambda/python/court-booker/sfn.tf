resource "aws_cloudwatch_log_group" "sfn" {
  # checkov:skip=CKV_AWS_158:Default AWS-managed encryption is enough for a weekly state machine.
  # checkov:skip=CKV_AWS_338:14 days matches the booker log group.
  name              = "/aws/vendedlogs/states/court-booker-api"
  retention_in_days = 14
}

data "aws_iam_policy_document" "sfn_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name               = "court-booker-api-sfn"
  assume_role_policy = data.aws_iam_policy_document.sfn_trust.json
}

data "aws_iam_policy_document" "sfn" {
  statement {
    sid       = "InvokeBooker"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = ["arn:aws:lambda:${var.region}:${var.aws_account_id}:function:court-booker-api", "arn:aws:lambda:${var.region}:${var.aws_account_id}:function:court-booker-api-calendar-writer"]
  }

  dynamic "statement" {
    for_each = local.ack_enabled ? [1] : []
    content {
      sid       = "StartAckWindow"
      effect    = "Allow"
      actions   = ["states:StartExecution"]
      resources = [local.ack_state_machine_arn]
    }
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

resource "aws_iam_role_policy" "sfn" {
  # checkov:skip=CKV_AWS_355:Step Functions log delivery APIs require Resource '*'.
  # checkov:skip=CKV_AWS_356:Step Functions log delivery APIs require Resource '*'.
  name   = "court-booker-api-sfn"
  role   = aws_iam_role.sfn.id
  policy = data.aws_iam_policy_document.sfn.json
}

locals {
  ack_state_machine_arn = "arn:aws:states:${var.region}:${var.aws_account_id}:stateMachine:court-booker-api-ack"

  # Everything ack-related is null/empty when local.ack_enabled is false, so the
  # rendered booking definition stays byte-identical to the pre-ack workflow.
  ack_start_choice = local.ack_enabled ? {
    And = [
      { Variable = "$.status", StringEquals = "booked" },
      { Variable = "$.reservation_id", IsPresent = true }
    ]
    Next = "StartAckWindow"
  } : null

  ack_booker_states = local.ack_enabled ? {
    StartAckWindow = {
      Type     = "Task"
      Resource = "arn:aws:states:::states:startExecution"
      Parameters = {
        StateMachineArn = local.ack_state_machine_arn
        "Name.$"        = "States.Format('ack-{}', $.reservation_id)"
        "Input.$"       = "$"
      }
      ResultPath = null
      Catch = [
        { ErrorEquals = ["StepFunctions.ExecutionAlreadyExistsException"], ResultPath = null, Next = "PublishCalendar" },
        { ErrorEquals = ["States.ALL"], ResultPath = "$.ack_error", Next = "PublishCalendar" }
      ]
      Next = "PublishCalendar"
    }
    AckWindowStarted = {
      Type = "Choice"
      Choices = [
        { Variable = "$.ack_error", IsPresent = true, Next = "AckWindowNotStarted" }
      ]
      Default = "Complete"
    }
    AckWindowNotStarted = {
      Type  = "Fail"
      Error = "AckWindowNotStarted"
      Cause = "booking kept, ack window not started"
    }
  } : null

  # Only rendered into aws_sfn_state_machine.booker, which exists when local.zip_ready.
  booker_definition = jsonencode({
    Comment        = "Three API attempts, 60s apart. Wait is here so Lambda is not billed for sleep."
    StartAt        = "Book"
    TimeoutSeconds = 300
    States = merge({
      Book = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = one(aws_lambda_function.booker[*].arn)
          "Payload.$"  = "$"
        }
        Retry = [
          {
            ErrorEquals     = ["States.ALL"]
            IntervalSeconds = 60
            MaxAttempts     = 2
            BackoffRate     = 1
            JitterStrategy  = "NONE"
          }
        ]
        OutputPath = "$.Payload"
        Next       = "PublishCalendarIfSuccessful"
      }
      PublishCalendarIfSuccessful = {
        Type = "Choice"
        Choices = [for choice in [
          {
            And = [
              { Variable = "$.dry_run", IsPresent = true },
              { Variable = "$.dry_run", BooleanEquals = true }
            ]
            Next = "Complete"
          },
          local.ack_start_choice,
          {
            Or = [
              { Variable = "$.status", StringEquals = "booked" },
              { Variable = "$.status", StringEquals = "already_held" },
              { Variable = "$.status", StringEquals = "cancelled" }
            ]
            Next = "PublishCalendar"
          }
        ] : choice if choice != null]
        Default = "Complete"
      }
      PublishCalendar = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = try(aws_lambda_function.calendar["writer"].arn, null)
          "Payload.$"  = "$"
        }
        ResultPath = null
        Retry      = [{ ErrorEquals = ["States.ALL"], IntervalSeconds = 2, MaxAttempts = 2, BackoffRate = 2 }]
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = null, Next = "CalendarPublicationFailed" }]
        Next       = local.ack_enabled ? "AckWindowStarted" : "Complete"
      }
      CalendarPublicationFailed = {
        Type  = "Fail"
        Error = "CalendarPublicationFailed"
        Cause = "booking confirmed, calendar publication failed"
      }
      Complete = { Type = "Succeed" }
    }, local.ack_booker_states)
  })
}

resource "aws_sfn_state_machine" "booker" {
  # checkov:skip=CKV_AWS_284:X-Ray is skipped to keep a once-a-week path cheap.
  # checkov:skip=CKV_AWS_285:ERROR-level CloudWatch logs are enough; ALL plus execution data would store weekly booking payloads.
  count = local.zip_ready ? 1 : 0

  name     = "court-booker-api"
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }

  definition = local.booker_definition

  depends_on = [aws_iam_role_policy.sfn]
}
