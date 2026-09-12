# This CA is independent of the existing ECR CA. Only its PUBLIC certificate
# enters state. Required input prevents omission from silently deleting identity.
resource "aws_rolesanywhere_trust_anchor" "backup" {
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
        ArnEquals = { "aws:SourceArn" = aws_rolesanywhere_trust_anchor.backup.arn }
        StringEquals = {
          "aws:SourceAccount"               = var.aws_account_id
          "aws:PrincipalTag/x509Subject/CN" = var.backup_certificate_common_name
        }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "upload" {
  role       = aws_iam_role.upload.name
  policy_arn = aws_iam_policy.upload.arn
}

resource "aws_rolesanywhere_profile" "backup" {
  name             = "homelab-backup-upload"
  enabled          = var.backup_identity_enabled
  duration_seconds = 3600
  role_arns        = [aws_iam_role.upload.arn]
}
