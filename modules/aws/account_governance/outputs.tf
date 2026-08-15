output "cloudtrail_arn" {
  value       = aws_cloudtrail.account.arn
  description = "Multi-region management-event trail. Confirm SNS opt-in mail for security alerts."
}

output "guardduty_detector_id" {
  value = aws_guardduty_detector.this.id
}

output "security_alerts_topic_arn" {
  value       = aws_sns_topic.security_alerts.arn
  description = "SNS topic for GuardDuty findings and EventBridge IAM/root alerts. Confirm the subscription email."
}

output "budget_reports_stack_id" {
  value       = aws_cloudformation_stack.budget_reports.id
  description = "Nested stack that emails daily, weekly, and monthly Cost Explorer summaries to governance_alert_email."
}
