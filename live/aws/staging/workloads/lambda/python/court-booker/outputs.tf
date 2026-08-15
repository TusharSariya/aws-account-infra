output "zip_bucket" {
  value       = data.aws_s3_bucket.zips.id
  description = "Account-level lambda-releases bucket. Pin booker_api_zip_key to stable/<name>/<sha>.zip."
}

output "secret_arn" {
  value       = data.aws_secretsmanager_secret.my_y.arn
  description = "Reuses staging/court-booker/my-y from the Playwright stack."
}

output "lambda_function_name" {
  value       = try(aws_lambda_function.booker[0].function_name, null)
  description = "null until booker_api_zip_key is set."
}

output "state_machine_arn" {
  value       = try(aws_sfn_state_machine.booker[0].arn, null)
  description = "null until booker_api_zip_key is set."
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
