output "state" {
  value = {
    bucket_name = aws_s3_bucket.external_state.id
    kms_key_arn = aws_kms_key.external_state.arn
  }
}

output "journal_table_name" {
  value = aws_dynamodb_table.journal.name
}

output "state_lock_table_name" {
  value = aws_dynamodb_table.state_locks.name
}

output "reconciler_role_arn" {
  value = aws_iam_role.reconciler.arn
}
