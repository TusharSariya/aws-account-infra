output "backup_bucket_name" {
  value       = module.rag_backups.s3_bucket_id
  description = "Target for the RAG repo's backup_to_s3.sh."
}

output "backup_bucket_kms_key_arn" {
  value = module.rag_backups.kms_key_arn
}

output "backup_catalog_table_name" {
  value       = aws_dynamodb_table.rag_backup_catalog.name
  description = "DynamoDB catalog the RAG repo's backup harness dual-writes (set RAG_BACKUP_CATALOG_TABLE)."
}

output "backup_catalog_table_arn" {
  value = aws_dynamodb_table.rag_backup_catalog.arn
}

output "ecr_repo_urls" {
  value       = { for k, m in module.ecr : k => m.repository_url }
  description = "Map of image name → ECR URL, consumed by the RAG repo's release_image.sh."
}

output "ecr_push_role_arn" {
  value       = aws_iam_role.github_ecr_push.arn
  description = "role-to-assume for the excalidraw-tf-rag repo's build/push CI workflow."
}

# --- Desktop backup-agent credentials (scoped to the rag-backups bucket) ---
output "rag_backup_access_key_id" {
  value       = aws_iam_access_key.rag_backup.id
  description = "Access key ID for the desktop's ~/.aws/credentials [rag-backup] profile."
}

output "rag_backup_secret_access_key" {
  value       = aws_iam_access_key.rag_backup.secret
  sensitive   = true
  description = "Retrieve with: tofu output -raw rag_backup_secret_access_key"
}

# test: exercise the apply button (no resource change)
