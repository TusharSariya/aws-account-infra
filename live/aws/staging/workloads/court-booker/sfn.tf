resource "aws_cloudwatch_log_group" "sfn" {
  # checkov:skip=CKV_AWS_158:Default AWS-managed encryption is enough for a weekly state machine.
  # checkov:skip=CKV_AWS_338:14 days matches the booker log group.
  name              = "/aws/vendedlogs/states/court-booker"
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
  name               = "court-booker-sfn"
  assume_role_policy = data.aws_iam_policy_document.sfn_trust.json
}

data "aws_iam_policy_document" "sfn" {
  statement {
    sid       = "InvokeBooker"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = ["arn:aws:lambda:${var.region}:${var.aws_account_id}:function:court-booker"]
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
  name   = "court-booker-sfn"
  role   = aws_iam_role.sfn.id
  policy = data.aws_iam_policy_document.sfn.json
}

resource "aws_sfn_state_machine" "booker" {
  # checkov:skip=CKV_AWS_284:X-Ray is skipped to keep a once-a-week path cheap.
  count = var.booker_image_tag != "" ? 1 : 0

  name     = "court-booker"
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }

  definition = jsonencode({
    Comment        = "Three Playwright attempts, 60s apart. Wait is here so Lambda is not billed for sleep."
    StartAt        = "Book"
    TimeoutSeconds = 360
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
            ErrorEquals     = ["States.ALL"]
            IntervalSeconds = 60
            MaxAttempts     = 2
            BackoffRate     = 1
            JitterStrategy  = "NONE"
          }
        ]
        OutputPath = "$.Payload"
        End        = true
      }
    }
  })

  depends_on = [aws_iam_role_policy.sfn]
}
