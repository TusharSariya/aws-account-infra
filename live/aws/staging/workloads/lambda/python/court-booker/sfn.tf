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
    resources = ["arn:aws:lambda:${var.region}:${var.aws_account_id}:function:court-booker-api"]
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

  definition = jsonencode({
    Comment        = "Retry only Lambda service failures and pre-submit closed responses. Ambiguous booking outcomes are never retried."
    StartAt        = "Book"
    TimeoutSeconds = 180
    States = {
      Book = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.booker[0].arn
          "Payload.$"  = "$"
        }
        Retry = [
          {
            ErrorEquals = [
              "Lambda.ServiceException",
              "Lambda.SdkClientException",
            ]
            IntervalSeconds = 2
            MaxAttempts     = 2
            BackoffRate     = 2
            JitterStrategy  = "FULL"
          },
          {
            ErrorEquals     = ["RetryableBookingFailed"]
            IntervalSeconds = 60
            MaxAttempts     = 2
            BackoffRate     = 1
            JitterStrategy  = "FULL"
          }
        ]
        OutputPath = "$.Payload"
        End        = true
      }
    }
  })

  depends_on = [aws_iam_role_policy.sfn]
}
