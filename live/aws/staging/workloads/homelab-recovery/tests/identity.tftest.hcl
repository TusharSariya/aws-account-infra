mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_resource "aws_iam_policy" {
    defaults = { arn = "arn:aws:iam::992382747916:policy/mock-policy" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::992382747916:role/homelab/homelab-recovery-upload" }
  }
  mock_resource "aws_rolesanywhere_trust_anchor" {
    defaults = { arn = "arn:aws:rolesanywhere:us-east-1:992382747916:trust-anchor/11111111-1111-1111-1111-111111111111" }
  }
}

variables {
  aws_account_id                 = "992382747916"
  aws_profile                    = ""
  backup_ca_certificate_pem      = "-----BEGIN CERTIFICATE-----\nmock-public-certificate\n-----END CERTIFICATE-----"
  backup_certificate_common_name = "homelab-backup-uploader-01"
}

run "upload_identity_is_scoped" {
  command = apply
  assert {
    condition = (
      jsondecode(aws_iam_role.upload.assume_role_policy).Statement[0].Principal.Service == "rolesanywhere.amazonaws.com" &&
      jsondecode(aws_iam_role.upload.assume_role_policy).Statement[0].Condition.ArnEquals["aws:SourceArn"] == aws_rolesanywhere_trust_anchor.backup.arn &&
      jsondecode(aws_iam_role.upload.assume_role_policy).Statement[0].Condition.StringEquals["aws:SourceAccount"] == "992382747916" &&
      jsondecode(aws_iam_role.upload.assume_role_policy).Statement[0].Condition.StringEquals["aws:PrincipalTag/x509Subject/CN"] == "homelab-backup-uploader-01"
    )
    error_message = "Trust must restrict the service, account, anchor and exact certificate identity."
  }
  assert {
    condition = (
      aws_iam_role.upload.permissions_boundary == aws_iam_policy.upload.arn &&
      aws_iam_role_policy_attachment.upload.policy_arn == aws_iam_policy.upload.arn &&
      aws_iam_role_policy_attachment.upload.role == aws_iam_role.upload.name &&
      toset(aws_rolesanywhere_profile.backup.role_arns) == toset([aws_iam_role.upload.arn]) &&
      aws_rolesanywhere_profile.backup.duration_seconds == 3600 &&
      aws_iam_role.upload.max_session_duration == 3600
    )
    error_message = "Only the bounded upload role may be issued, for at most one hour."
  }
}

run "disable_new_sessions" {
  command = plan
  variables { backup_identity_enabled = false }
  assert {
    condition     = !aws_rolesanywhere_trust_anchor.backup.enabled && !aws_rolesanywhere_profile.backup.enabled
    error_message = "The emergency switch must disable both anchor and profile."
  }
}

run "rotate_identity" {
  command = plan
  variables { backup_certificate_common_name = "homelab-backup-uploader-02" }
  assert {
    condition     = jsondecode(aws_iam_role.upload.assume_role_policy).Statement[0].Condition.StringEquals["aws:PrincipalTag/x509Subject/CN"] == "homelab-backup-uploader-02"
    error_message = "Rotation must replace the permitted CN, not retain the old identity."
  }
}

run "reject_missing_ca" {
  command = plan
  variables { backup_ca_certificate_pem = "" }
  expect_failures = [var.backup_ca_certificate_pem]
}

run "reject_wildcard_identity" {
  command = plan
  variables { backup_certificate_common_name = "*" }
  expect_failures = [var.backup_certificate_common_name]
}
