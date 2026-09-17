# Separate from Object-Locked recovery material: latest is retained indefinitely.
module "postgres" {
  source                      = "../../../../../modules/aws/encrypted_s3_bucket"
  bucket_name                 = "homelab-postgres-${var.aws_account_id}-${var.region}"
  kms_description             = "Homelab PostgreSQL logical backups"
  kms_deletion_window_in_days = 30
  protect_bucket_deletion     = true
  lifecycle_rules = [
    { id     = "latest-superseded-seven-days", enabled = true,
      filter = { prefix = "apps-db/latest.tar.gz" },
    noncurrent_version_expiration = { days = 7 } },
    { id     = "staging-one-day", enabled = true,
      filter = { prefix = "staging/" }, expiration = { days = 1 },
    noncurrent_version_expiration = { days = 1 } },
    { id = "abort-incomplete-one-day", enabled = true,
    abort_incomplete_multipart_upload_days = 1 }
  ]
  tags = merge(var.default_tags, { component = "homelab-postgres" })
}

variable "postgres_ca_certificate_pem" {
  type        = string
  default     = ""
  description = "Public dedicated signing CA. Never a private key. Empty disables enrollment."
  validation {
    condition = var.postgres_ca_certificate_pem == "" || (
      startswith(trimspace(var.postgres_ca_certificate_pem), "-----BEGIN CERTIFICATE-----") &&
      endswith(trimspace(var.postgres_ca_certificate_pem), "-----END CERTIFICATE-----") &&
    !strcontains(var.postgres_ca_certificate_pem, "PRIVATE KEY"))
    error_message = "Supply only the public PEM CA certificate."
  }
}
variable "postgres_certificate_common_name" {
  type    = string
  default = "homelab-postgres-backup-01"
  validation {
    condition     = can(regex("^homelab-postgres-backup-[a-z0-9-]{1,32}$", var.postgres_certificate_common_name))
    error_message = "Use a dedicated homelab-postgres-backup- identity."
  }
}
variable "postgres_identity_enabled" {
  type    = bool
  default = true
}
locals {
  postgres_enrolled = var.postgres_ca_certificate_pem != ""
  postgres_alerts   = "arn:aws:sns:${var.region}:${var.aws_account_id}:account-security-alerts"
}
resource "aws_rolesanywhere_trust_anchor" "postgres" {
  count   = local.postgres_enrolled ? 1 : 0
  name    = "homelab-postgres-backup"
  enabled = var.postgres_identity_enabled
  source {
    source_type = "CERTIFICATE_BUNDLE"
    source_data { x509_certificate_data = var.postgres_ca_certificate_pem }
  }
  lifecycle { prevent_destroy = true }
}
resource "aws_iam_policy" "postgres_backup" {
  name = "homelab-postgres-backup"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"],
      Resource = ["${module.postgres.s3_bucket_arn}/apps-db/latest.tar.gz", "${module.postgres.s3_bucket_arn}/staging/*"] },
      { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = module.postgres.kms_key_arn,
      Condition = { StringEquals = { "kms:ViaService" = "s3.${var.region}.amazonaws.com", "kms:CallerAccount" = var.aws_account_id } } },
      { Effect = "Allow", Action = "cloudwatch:PutMetricData", Resource = "*",
      Condition = { StringEquals = { "cloudwatch:namespace" = "Homelab/Postgres" } } }
    ]
  })
}
resource "aws_iam_role" "postgres_backup" {
  count                = local.postgres_enrolled ? 1 : 0
  name                 = "homelab-postgres-backup"
  path                 = "/homelab/"
  max_session_duration = 3600
  permissions_boundary = aws_iam_policy.postgres_backup.arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow", Principal = { Service = "rolesanywhere.amazonaws.com" },
      Action = ["sts:AssumeRole", "sts:TagSession", "sts:SetSourceIdentity"],
      Condition = {
        ArnEquals    = { "aws:SourceArn" = aws_rolesanywhere_trust_anchor.postgres[0].arn }
        StringEquals = { "aws:SourceAccount" = var.aws_account_id, "aws:PrincipalTag/x509Subject/CN" = var.postgres_certificate_common_name }
      }
    }]
  })
}
resource "aws_iam_role_policy_attachment" "postgres_backup" {
  count      = local.postgres_enrolled ? 1 : 0
  role       = aws_iam_role.postgres_backup[0].name
  policy_arn = aws_iam_policy.postgres_backup.arn
}
resource "aws_rolesanywhere_profile" "postgres" {
  count            = local.postgres_enrolled ? 1 : 0
  name             = "homelab-postgres-backup"
  enabled          = var.postgres_identity_enabled
  duration_seconds = 3600
  role_arns        = [aws_iam_role.postgres_backup[0].arn]
}
resource "aws_cloudwatch_metric_alarm" "postgres_stale" {
  alarm_name          = "homelab-postgres-backup-stale"
  alarm_description   = "No verified PostgreSQL backup in approximately 30 hours"
  comparison_operator = "LessThanThreshold"
  threshold           = 1
  evaluation_periods  = 30
  datapoints_to_alarm = 30
  treat_missing_data  = "breaching"
  alarm_actions       = [local.postgres_alerts]
  ok_actions          = [local.postgres_alerts]
  metric_query {
    id          = "success"
    return_data = false
    metric {
      namespace   = "Homelab/Postgres"
      metric_name = "BackupSuccess"
      dimensions  = { Cluster = "apps-db" }
      period      = 3600
      stat        = "Sum"
    }
  }
  metric_query {
    id          = "heartbeat"
    expression  = "FILL(success, 0)"
    return_data = true
  }
}
resource "aws_cloudwatch_metric_alarm" "postgres_failure" {
  for_each            = toset(["BackupFailure", "CertificateExpiring"])
  alarm_name          = "homelab-postgres-${each.key}"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"
  namespace           = "Homelab/Postgres"
  metric_name         = each.key
  dimensions          = { Cluster = "apps-db" }
  period              = 300
  statistic           = "Maximum"
  alarm_actions       = [local.postgres_alerts]
}
output "postgres_backup" {
  value = {
    bucket           = module.postgres.s3_bucket_id
    kms_key_arn      = module.postgres.kms_key_arn
    trust_anchor_arn = one(aws_rolesanywhere_trust_anchor.postgres[*].arn)
    profile_arn      = one(aws_rolesanywhere_profile.postgres[*].arn)
    role_arn         = one(aws_iam_role.postgres_backup[*].arn)
  }
}
