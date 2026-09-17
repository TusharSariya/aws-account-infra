mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}
run "postgres_retention_and_least_privilege" {
  command = apply
  variables {
    aws_account_id                 = "992382747916"
    aws_profile                    = ""
    create_backup_identity         = false
    backup_certificate_common_name = "homelab-backup-uploader-01"
  }
  assert {
    condition = toset(jsondecode(aws_iam_policy.postgres_backup.policy).Statement[0].Action) == toset([
      "s3:PutObject", "s3:GetObject", "s3:GetObjectVersion", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"
    ])
    error_message = "Workload must never delete objects or administer the bucket."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.postgres_stale.evaluation_periods == 30 && aws_cloudwatch_metric_alarm.postgres_stale.treat_missing_data == "breaching"
    error_message = "Missing success must alert at approximately 30 hours."
  }
  assert {
    condition     = endswith(jsondecode(aws_iam_policy.postgres_backup.policy).Statement[0].Resource[0], "/apps-db/latest.tar.gz")
    error_message = "PostgreSQL must not reuse the Object-Locked recovery bucket."
  }
}
