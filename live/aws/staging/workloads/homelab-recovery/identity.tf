# Optional automated uploader. Manual backups use the independent AWS admin login.
# Only the public CA certificate enters state when this identity is enabled.
resource "aws_rolesanywhere_trust_anchor" "backup" {
  count   = var.create_backup_identity ? 1 : 0
  name    = "homelab-backup"
  enabled = var.backup_identity_enabled
  source {
    source_type = "CERTIFICATE_BUNDLE"
    source_data {
      x509_certificate_data = var.backup_ca_certificate_pem
    }
  }
}

resource "aws_iam_role" "upload" {
  count                = var.create_backup_identity ? 1 : 0
  name                 = "homelab-recovery-upload"
  path                 = "/homelab/"
  max_session_duration = 3600
  permissions_boundary = aws_iam_policy.upload.arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "rolesanywhere.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession", "sts:SetSourceIdentity"]
      Condition = {
        ArnEquals = { "aws:SourceArn" = aws_rolesanywhere_trust_anchor.backup[0].arn }
        StringEquals = {
          "aws:SourceAccount"               = var.aws_account_id
          "aws:PrincipalTag/x509Subject/CN" = var.backup_certificate_common_name
        }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "upload" {
  count      = var.create_backup_identity ? 1 : 0
  role       = aws_iam_role.upload[0].name
  policy_arn = aws_iam_policy.upload.arn
}

resource "aws_rolesanywhere_profile" "backup" {
  count            = var.create_backup_identity ? 1 : 0
  name             = "homelab-backup-upload"
  enabled          = var.backup_identity_enabled
  duration_seconds = 3600
  role_arns        = [aws_iam_role.upload[0].arn]
}
