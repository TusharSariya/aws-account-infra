# Existing account-level GitHub OIDC provider; no long-lived AWS credentials.
resource "aws_iam_role" "daily_backup" {
  name                 = "homelab-etcd-backup"
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = "arn:aws:iam::${var.aws_account_id}:oidc-provider/token.actions.githubusercontent.com" }
      Condition = { StringEquals = {
        "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        "token.actions.githubusercontent.com:sub" = "repo:TusharSariyaOrg/aws-account-infra:environment:prod"
      } }
    }]
  })
}

resource "aws_iam_role_policy" "daily_backup" {
  name = "etcd-upload-verify-heartbeat"
  role = aws_iam_role.daily_backup.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion"]
        Resource = "${module.recovery.s3_bucket_arn}/etcd/latest.tar.gz.age"
      },
      {
        Effect    = "Allow"
        Action    = "cloudwatch:PutMetricData"
        Resource  = "*"
        Condition = { StringEquals = { "cloudwatch:namespace" = "Homelab/Recovery" } }
      }
    ]
  })
}

# Independent of GitHub schedules: a missing success heartbeat is a failure.
resource "aws_cloudwatch_metric_alarm" "etcd_backup_stale" {
  alarm_name          = "homelab-etcd-backup-stale"
  alarm_description   = "No verified etcd backup success in approximately 30 hours"
  comparison_operator = "LessThanThreshold"
  threshold           = 1
  evaluation_periods  = 30
  datapoints_to_alarm = 30
  treat_missing_data  = "breaching"
  alarm_actions       = ["arn:aws:sns:${var.region}:${var.aws_account_id}:account-security-alerts"]
  ok_actions          = ["arn:aws:sns:${var.region}:${var.aws_account_id}:account-security-alerts"]
  metric_query {
    id          = "success"
    return_data = false
    metric {
      namespace   = "Homelab/Recovery"
      metric_name = "EtcdBackupSuccess"
      dimensions  = { Cluster = "homelab" }
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

output "daily_backup_role_arn" {
  value = aws_iam_role.daily_backup.arn
}
