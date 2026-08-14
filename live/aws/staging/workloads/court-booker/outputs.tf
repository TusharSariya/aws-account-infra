output "ecr_repository_url" {
  value       = module.ecr.repository_url
  description = "Push target for scripts/ecr-image.sh court-booker."
}

output "secret_arn" {
  value       = aws_secretsmanager_secret.my_y.arn
  description = "Put My Y JSON here; never commit the value."
}

output "lambda_function_name" {
  value       = try(aws_lambda_function.booker[0].function_name, null)
  description = "null until booker_image_tag is set."
}

output "state_machine_arn" {
  value       = try(aws_sfn_state_machine.booker[0].arn, null)
  description = "null until booker_image_tag is set."
}

output "schedule_names" {
  value = [for schedule in aws_scheduler_schedule.weekly : schedule.name]
}

output "alert_topic_arn" {
  value       = aws_sns_topic.alerts.arn
  description = "CloudWatch alarm target; a Lambda forwards to SES."
}

output "alert_email" {
  value       = var.alert_email
  description = "Confirm the SES verification email before alarms can deliver."
}
