# Least-privilege identity for the desktop GPU box (the authoritative home of the
# corpus + CUDA/gemini/jina indexes) to push & restore RAG backups. Scoped to
# ONLY the rag-backups bucket and its KMS key — it can touch nothing else in the
# account. The Mac keeps using its admin/assume-role creds for its mlx-* backups.

resource "aws_iam_user" "rag_backup" {
  # checkov:skip=CKV_AWS_273:Intentional long-lived programmatic identity for the desktop GPU box (no human/SSO path); scoped to only this bucket + its CMK.
  name = "rag-backup"
  path = "/service/"
  tags = { component = "rag-backups" }
}

data "aws_iam_policy_document" "rag_backup" {
  statement {
    sid       = "ListBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:ListBucketVersions", "s3:GetBucketLocation"]
    resources = [module.rag_backups.s3_bucket_arn]
  }

  statement {
    sid    = "ObjectReadWrite"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
      # Run-stamped derived artifacts tier to GLACIER (Flexible) via lifecycle, so a
      # restore must thaw them first — GetObject alone can't read a GLACIER object.
      "s3:RestoreObject",
      # Object tags carry triage identity (tool/category/name/run_id) and drive the
      # run-stamped lifecycle rule, so the agent must set & read them.
      "s3:PutObjectTagging",
      "s3:GetObjectTagging",
      "s3:GetObjectVersionTagging",
    ]
    resources = ["${module.rag_backups.s3_bucket_arn}/*"]
  }

  # Dual-write the backup catalog: one row per artifact per run, plus by-run GSI
  # reads for snapshot/as-of-T restores. Scoped to only this table + its indexes.
  # No BatchWriteItem/DeleteItem: the catalog is append-only immutable history, and
  # BatchWriteItem would smuggle in delete capability the agent must not have.
  statement {
    sid    = "BackupCatalog"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:DescribeTable",
    ]
    resources = [
      aws_dynamodb_table.rag_backup_catalog.arn,
      "${aws_dynamodb_table.rag_backup_catalog.arn}/index/*",
    ]
  }

  # SSE-KMS read/write needs data-key ops on the bucket's CMK (and only that key).
  statement {
    sid    = "BucketKmsKey"
    effect = "Allow"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
    ]
    resources = [module.rag_backups.kms_key_arn]
  }
}

resource "aws_iam_user_policy" "rag_backup" {
  # checkov:skip=CKV_AWS_40:Policy is deliberately attached to the single-purpose service user above (there is no group/role for this programmatic identity).
  name   = "rag-backup-bucket-access"
  user   = aws_iam_user.rag_backup.name
  policy = data.aws_iam_policy_document.rag_backup.json
}

# Long-lived key for the desktop's ~/.aws/credentials. Tightly scoped above, so a
# leak only exposes this one backup bucket. Secret lives in tf state (retrieve with
# `tofu output -raw rag_backup_secret_access_key`); rotate by tainting this resource.
resource "aws_iam_access_key" "rag_backup" {
  user = aws_iam_user.rag_backup.name
}
