resource "aws_scheduler_schedule_group" "digest" { name = "technology-digest" }
resource "aws_iam_role" "scheduler" {
  name = "technology-digest-scheduler"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole",
    Condition = { StringEquals = { "aws:SourceAccount" = var.aws_account_id }, ArnEquals = { "aws:SourceArn" = aws_scheduler_schedule_group.digest.arn } }
  }] })
}
resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [for f in aws_lambda_function.digest : f.arn] },
    { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = aws_sqs_queue.failures.arn }
  ] })
}
locals {
  schedules = {
    hourly = { expression = "cron(0 * * * ? *)", handler = "collector", input = {} }
    daily  = { expression = "cron(0 8 * * ? *)", handler = "digester", input = { kind = "daily", scheduled_time = "<aws.scheduler.scheduled-time>" } }
    weekly = { expression = "cron(15 8 ? * MON *)", handler = "digester", input = { kind = "weekly", scheduled_time = "<aws.scheduler.scheduled-time>" } }
  }
}
resource "aws_scheduler_schedule" "digest" {
  # checkov:skip=CKV_AWS_297:Schedule payloads contain only digest kind and invocation timestamp.
  for_each                     = local.schedules
  name                         = "technology-digest-${each.key}"
  group_name                   = aws_scheduler_schedule_group.digest.name
  schedule_expression          = each.value.expression
  schedule_expression_timezone = each.key == "hourly" ? "UTC" : "America/St_Johns"
  state                        = var.schedules_enabled ? "ENABLED" : "DISABLED"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_lambda_function.digest[each.value.handler].arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode(each.value.input)
    dead_letter_config { arn = aws_sqs_queue.failures.arn }
    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 2
    }
  }
  depends_on = [aws_iam_role_policy.scheduler]
}
