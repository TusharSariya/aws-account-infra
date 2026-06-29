output "backup_bucket_name" {
  value       = module.rag_backups.s3_bucket_id
  description = "Target for the RAG repo's backup_to_s3.sh."
}

output "backup_bucket_kms_key_arn" {
  value = module.rag_backups.kms_key_arn
}

output "ecr_repo_urls" {
  value       = { for k, m in module.ecr : k => m.repository_url }
  description = "Map of image name → ECR URL, consumed by the RAG repo's release_image.sh."
}
