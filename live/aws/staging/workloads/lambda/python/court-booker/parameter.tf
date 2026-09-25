data "aws_kms_alias" "ssm" {
  name = "alias/aws/ssm"
}

resource "aws_ssm_parameter" "my_y" {
  # checkov:skip=CKV_AWS_337:AWS-managed alias/aws/ssm encrypts a standard SecureString without a $1/month CMK.
  name        = "/staging/court-booker-api/my-y"
  description = "My Y username/password JSON for the HTTP court-booker-api Lambda. Put with scripts/court-booker-put-secret.sh, never tfvars."
  type        = "SecureString"
  tier        = "Standard"
  key_id      = "alias/aws/ssm"
  value       = "UNSET"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "calendar_private_key" {
  # checkov:skip=CKV_AWS_337:AWS-managed alias/aws/ssm encrypts a standard SecureString without a $1/month CMK.
  name        = "/staging/court-booker-api/calendar-private-key"
  description = "Private court-booker calendar URL key. Set or rotate with scripts/court-booker-calendar-key.sh, never tfvars. UNSET keeps the private feed closed."
  type        = "SecureString"
  tier        = "Standard"
  key_id      = "alias/aws/ssm"
  value       = "UNSET"

  lifecycle {
    ignore_changes = [value]
  }
}
