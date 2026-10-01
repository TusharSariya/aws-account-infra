# Secret values deliberately have no Terraform resources or data sources.
resource "aws_kms_key" "oauth" {
  count                   = var.oauth_secrets == null ? 0 : 1
  description             = "${var.service_name} OAuth credential encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "EnableAccountIAMPermissions"
      Effect    = "Allow"
      Principal = { AWS = "arn:aws:iam::${var.aws_account_id}:root" }
      Action    = "kms:*"
      Resource  = "*"
    }]
  })
  lifecycle { prevent_destroy = true }
}

resource "aws_secretsmanager_secret" "oauth" {
  # checkov:skip=CKV2_AWS_57:OAuth tokens rotate hourly under the snapshot lease; iRacing client secrets are issuer-managed and cannot use Secrets Manager rotation.
  for_each = var.oauth_secrets == null ? {} : {
    client = var.oauth_secrets.client_name
    tokens = var.oauth_secrets.token_name
  }
  name                    = each.value
  kms_key_id              = aws_kms_key.oauth[0].arn
  recovery_window_in_days = 30
  lifecycle { prevent_destroy = true }
}

resource "aws_iam_role_policy" "oauth" {
  count = var.oauth_secrets == null ? 0 : 1
  role  = aws_iam_role.lambda["sync"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [for secret in aws_secretsmanager_secret.oauth : secret.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:PutSecretValue"]
        Resource = aws_secretsmanager_secret.oauth["tokens"].arn
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = aws_kms_key.oauth[0].arn
        Condition = {
          StringEquals = {
            "kms:ViaService"                  = "secretsmanager.${var.region}.amazonaws.com"
            "kms:EncryptionContext:SecretARN" = [for secret in aws_secretsmanager_secret.oauth : secret.arn]
          }
        }
      }
    ]
  })
}

resource "aws_scheduler_schedule" "auth" {
  # checkov:skip=CKV_AWS_297:Payload contains only action=auth; no credentials. Matches the existing calendar schedules.
  count               = var.oauth_secrets == null ? 0 : (var.oauth_secrets.maintenance_enabled ? 1 : 0)
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

output "oauth_secret_names" {
  value = { for name, secret in aws_secretsmanager_secret.oauth : name => secret.name }
}
