resource "aws_secretsmanager_secret" "my_y" {
  # checkov:skip=CKV2_AWS_57:Personal My Y password; rotation would lock the booker until a human updates Upace. Put the value with the AWS CLI, never tfvars.
  # checkov:skip=CKV_AWS_149:AWS-managed Secrets Manager encryption is enough; a dedicated CMK would add a monthly KMS charge for one secret.
  name                    = "staging/court-booker/my-y"
  recovery_window_in_days = 7
  description             = "My Y username/password JSON for the court-booker Lambda."
}
