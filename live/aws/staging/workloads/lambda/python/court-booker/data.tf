data "aws_ses_email_identity" "alerts" {
  email = var.alert_email
}
