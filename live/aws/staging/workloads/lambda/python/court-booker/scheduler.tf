resource "aws_scheduler_schedule_group" "booker" {
  name = "court-booker-api"
}

resource "aws_scheduler_schedule" "weekly" {
  # checkov:skip=CKV_AWS_297:A dedicated CMK for one weekly cron payload is not worth the monthly KMS charge.
  for_each = local.weekly_cron

  name                         = "court-booker-api-${each.key}"
  group_name                   = aws_scheduler_schedule_group.booker.name
  description                  = "Unlock ${each.value.activity} ${each.value.weekday} ${each.value.time} via API; Step Functions retries 3 times, 60s apart"
  schedule_expression          = "cron(${each.value.cron_minute} ${each.value.cron_hour} ? * ${each.value.cron_dow} *)"
  schedule_expression_timezone = "America/St_Johns"
  state                        = var.api_schedule_enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_sfn_state_machine.booker[0].arn
    role_arn = aws_iam_role.scheduler.arn
    input = jsonencode({
      source       = "weekly"
      activity     = each.value.activity
      weekday      = each.value.weekday
      time         = each.value.time
      duration_min = each.value.duration_min
      people       = each.value.people
    })
    retry_policy {
      maximum_retry_attempts       = 0
      maximum_event_age_in_seconds = 60
    }
  }
}

resource "aws_scheduler_schedule" "oneshot" {
  # checkov:skip=CKV_AWS_297:A dedicated CMK for a one-shot validation payload is not worth the monthly KMS charge.
  for_each = local.oneshot

  name                         = "court-booker-api-oneshot-${each.key}"
  group_name                   = aws_scheduler_schedule_group.booker.name
  description                  = "One-shot API ${each.value.activity} ${each.value.date} ${each.value.time}; expected ${each.key}"
  schedule_expression          = "at(${each.value.invoke_at})"
  schedule_expression_timezone = "America/St_Johns"
  state                        = var.api_schedule_enabled ? "ENABLED" : "DISABLED"
  action_after_completion      = "DELETE"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_sfn_state_machine.booker[0].arn
    role_arn = aws_iam_role.scheduler.arn
    input = jsonencode({
      source       = "adhoc"
      activity     = each.value.activity
      date         = each.value.date
      time         = each.value.time
      duration_min = each.value.duration_min
      people       = each.value.people
    })
    retry_policy {
      maximum_retry_attempts       = 0
      maximum_event_age_in_seconds = 60
    }
  }
}
