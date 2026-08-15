data "aws_secretsmanager_secret" "my_y" {
  name = "staging/court-booker/my-y"
}

data "aws_ses_email_identity" "alerts" {
  email = var.alert_email
}
