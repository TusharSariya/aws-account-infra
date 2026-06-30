# RAG productionization infra: the durable cloud resources the RAG repo consumes.
# (The query server, Docker image, and backup scripts live in the RAG repo and read
# this stack's outputs.)

# --- Backup bucket: full corpus + indexes (~37 GB across RAG tools) ---------
module "rag_backups" {
  source = "../../modules/encrypted_s3_bucket"

  bucket_name = "rag-backups-${var.aws_account_id}-${var.region}"

  # Backups are nowhere near 1 TiB / 1M objects; relax the inherited alarms.
  bucket_size_bytes_threshold = 107374182400 # 100 GiB

  object_count_threshold = 2000000

  # Move noncurrent versions to cheaper storage; keep recent history cheaply.
  lifecycle_rules = [
    {
      id      = "backup-noncurrent-tiering"
      enabled = true
      # Reap orphaned multipart parts: the multi-GB index tarballs upload via
      # multipart, and a failed/aborted upload otherwise leaves billable fragments.
      abort_incomplete_multipart_upload_days = 7
      noncurrent_version_transition = [
        {
          days          = var.backup_noncurrent_transition_days
          storage_class = "STANDARD_IA"
        },
        {
          days          = var.backup_noncurrent_transition_days + 60
          storage_class = "GLACIER"
        },
      ]
    },
  ]

  tags = { component = "rag-backups" }
}

# --- ECR repos: one per RAG service image ----------------------------------
module "ecr" {
  source   = "../../modules/ecr_repository"
  for_each = toset(var.ecr_repos)

  name = each.value
  tags = { component = "rag" }
}
