# Backup catalog: a queryable index of every RAG backup artifact over time.
#
# The in-bucket `_catalog/runs/<run-id>.json` objects are the source of truth (a
# restore works from the bucket alone); this table is the convenience index the
# backup harness dual-writes so you can ask "what was profile X at time T, and
# with what config" without scanning every run manifest.
#
#   PK artifact = "<tool>/<category>/<name>"   (the logical artifact)
#   SK run_id   = "<UTC-compact>-<host>"        (sortable → latest / as-of-T)
#   GSI by-run  : run_id (HASH) + artifact (RANGE) → everything in one backup run
#
# Non-key attributes (s3_key, s3_version_id, sha256, size_bytes, content_sig,
# storage_class, config/provenance JSON, …) are schemaless and not declared here.

resource "aws_dynamodb_table" "rag_backup_catalog" {
  name         = "rag-backup-catalog"
  billing_mode = "PAY_PER_REQUEST" # backups are infrequent, bursty writes — no capacity to manage
  hash_key     = "artifact"
  range_key    = "run_id"

  attribute {
    name = "artifact"
    type = "S"
  }
  attribute {
    name = "run_id"
    type = "S"
  }

  # Query every artifact captured in a single backup run (whole-snapshot view).
  global_secondary_index {
    name            = "by-run"
    hash_key        = "run_id"
    range_key       = "artifact"
    projection_type = "ALL"
  }

  # Point-in-time recovery: the catalog is small but load-bearing for "as-of-T"
  # restores, so keep continuous backups (also satisfies CKV_AWS_28).
  point_in_time_recovery {
    enabled = true
  }

  # Encrypt at rest with the rag-backups CMK (the rag-backup user already holds
  # data-key perms on this key). Satisfies CKV_AWS_119.
  server_side_encryption {
    enabled     = true
    kms_key_arn = module.rag_backups.kms_key_arn
  }

  tags = { component = "rag-backups" }
}
