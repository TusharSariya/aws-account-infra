# Least-privilege identity for the desktop GPU box (the authoritative home of the
# corpus + CUDA/gemini/jina indexes) to push & restore RAG backups. Scoped to
# ONLY the rag-backups bucket and its KMS key — it can touch nothing else in the
# account. The Mac keeps using its admin/assume-role creds for its mlx-* backups.

resource "aws_iam_user" "rag_backup" {
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
    ]
    resources = ["${module.rag_backups.s3_bucket_arn}/*"]
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
