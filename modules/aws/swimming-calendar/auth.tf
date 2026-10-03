# Values are created by bootstrap/migration and rotated at runtime, never read
# into OpenTofu state. SecureString uses the AWS-managed alias/aws/ssm key.
locals {
  oauth_parameter_names = var.oauth_parameters == null ? {} : {
    client = var.oauth_parameters.client_name
    tokens = var.oauth_parameters.token_name
  }
  oauth_parameter_arns = {
    for name, path in local.oauth_parameter_names : name => "arn:aws:ssm:${var.region}:${var.aws_account_id}:parameter${path}"
  }
}

resource "aws_iam_role_policy" "oauth" {
  count = var.oauth_parameters == null ? 0 : 1
  role  = aws_iam_role.lambda["sync"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = values(local.oauth_parameter_arns)
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:PutParameter"]
        Resource = local.oauth_parameter_arns["tokens"]
      }
    ]
  })
}

resource "aws_scheduler_schedule" "auth" {
  # checkov:skip=CKV_AWS_297:Payload contains only action=auth; no credentials. Matches the existing calendar schedules.
  count               = var.oauth_parameters == null ? 0 : (var.oauth_parameters.maintenance_enabled ? 1 : 0)
  name                = "${var.service_name}-auth"
  schedule_expression = "rate(1 hour)"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_lambda_function.app["sync"].arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ action = "auth" })
    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 2
    }
    dead_letter_config { arn = aws_sqs_queue.failures.arn }
  }
}

output "oauth_parameter_names" {
  value = local.oauth_parameter_names
}
