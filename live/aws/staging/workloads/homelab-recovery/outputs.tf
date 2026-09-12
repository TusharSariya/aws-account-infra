output "bucket_name" {
  value = module.recovery.s3_bucket_id
}
output "kms_key_arn" {
  value = module.recovery.kms_key_arn
}
output "upload_policy_arn" {
  value = aws_iam_policy.upload.arn
}
output "restore_policy_arn" {
  value = aws_iam_policy.restore.arn
}

output "backup_trust_anchor_arn" {
  value = aws_rolesanywhere_trust_anchor.backup.arn
}
output "backup_profile_arn" {
  value = aws_rolesanywhere_profile.backup.arn
}
output "backup_upload_role_arn" {
  value = aws_iam_role.upload.arn
}
