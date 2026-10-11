locals {
  bootstrap_name = "zwift-calendar-history-bootstrap"
  bootstrap_arn  = "arn:aws:states:${var.region}:${var.aws_account_id}:stateMachine:${local.bootstrap_name}"
  sync_arn       = "arn:aws:lambda:${var.region}:${var.aws_account_id}:function:${module.calendar.sync_function}"
}

resource "aws_kms_key" "bootstrap_logs" {
  description             = "Encryption for Zwift historical bootstrap execution logs"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Sid = "AccountAdministration", Effect = "Allow", Principal = { AWS = "arn:aws:iam::${var.aws_account_id}:root" }, Action = "kms:*", Resource = "*" },
    { Sid       = "ScopedLogEncryption", Effect = "Allow", Principal = { Service = "logs.${var.region}.amazonaws.com" },
      Action    = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"], Resource = "*",
      Condition = { ArnEquals = { "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${var.region}:${var.aws_account_id}:log-group:/aws/vendedlogs/states/${local.bootstrap_name}" } }
    }
  ] })
}
resource "aws_cloudwatch_log_group" "bootstrap" {
  # checkov:skip=CKV_AWS_338:Seven days of sanitized execution logs; Standard execution history retains aggregate results for 90 days.
  name              = "/aws/vendedlogs/states/${local.bootstrap_name}"
  retention_in_days = 7
  kms_key_id        = aws_kms_key.bootstrap_logs.arn
}
resource "aws_iam_role" "bootstrap" {
  name = local.bootstrap_name
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Action = "sts:AssumeRole", Principal = { Service = "states.amazonaws.com" },
    Condition = { StringEquals = { "aws:SourceAccount" = var.aws_account_id }, ArnEquals = { "aws:SourceArn" = local.bootstrap_arn } }
  }] })
}
resource "aws_iam_role_policy" "bootstrap" {
  # checkov:skip=CKV_AWS_355:CloudWatch Logs delivery APIs require Resource '*'.
  # checkov:skip=CKV_AWS_356:CloudWatch Logs delivery APIs require Resource '*'.
  role = aws_iam_role.bootstrap.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [aws_lambda_function.history.arn, local.sync_arn] },
    { Effect = "Allow", Action = ["logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"], Resource = "*" }
  ] })
}
resource "aws_sfn_state_machine" "bootstrap" {
  # checkov:skip=CKV_AWS_284:Execution history, encrypted logs, and failure alarms cover this serial batch workflow without X-Ray.
  name     = local.bootstrap_name
  role_arn = aws_iam_role.bootstrap.arn
  type     = "STANDARD"
  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.bootstrap.arn}:*"
    include_execution_data = false
    level                  = "ALL"
  }
  definition = templatefile("${path.module}/bootstrap.asl.json", {
    history_arn = aws_lambda_function.history.arn
    sync_arn    = local.sync_arn
  })
  depends_on = [aws_iam_role_policy.bootstrap]
}
resource "aws_cloudwatch_metric_alarm" "bootstrap_failed" {
  for_each            = toset(["ExecutionsFailed", "ExecutionsTimedOut", "ExecutionsAborted"])
  alarm_name          = "${local.bootstrap_name}-${each.key}"
  alarm_description   = "Historical bootstrap stopped unexpectedly; inspect execution and resume saved progress"
  namespace           = "AWS/States"
  metric_name         = each.key
  dimensions          = { StateMachineArn = aws_sfn_state_machine.bootstrap.arn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.history.alerts_topic]
}
output "history_bootstrap_state_machine" { value = aws_sfn_state_machine.bootstrap.arn }
