mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}

run "backup_role_cannot_delete" {
  command = apply
  variables {
    aws_account_id                 = "992382747916"
    aws_profile                    = ""
    create_backup_identity         = false
    backup_certificate_common_name = "homelab-backup-uploader-01"
  }
  assert {
    condition     = jsondecode(aws_iam_role.daily_backup.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:TusharSariyaOrg/aws-account-infra:environment:prod"
    error_message = "Only the repository prod OIDC subject may assume the backup role."
  }
  assert {
    condition     = toset(jsondecode(aws_iam_role_policy.daily_backup.policy).Statement[0].Action) == toset(["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion"])
    error_message = "Backup role must not delete versions, change lifecycle or bypass retention."
  }
  assert {
    condition     = endswith(jsondecode(aws_iam_role_policy.daily_backup.policy).Statement[0].Resource, "/etcd/latest.tar.gz.age")
    error_message = "Backup access must target only the fixed etcd object key."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.etcd_backup_stale.treat_missing_data == "breaching" && aws_cloudwatch_metric_alarm.etcd_backup_stale.evaluation_periods == 30
    error_message = "A missing daily heartbeat must not silently pass."
  }
}
