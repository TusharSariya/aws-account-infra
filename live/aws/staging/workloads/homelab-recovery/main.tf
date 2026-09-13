# Bootstrap recovery inputs have no automatic expiry. Routine/monthly backups
# use distinct prefixes; retain noncurrent versions for the same retention window.
module "recovery" {
  source                      = "../../../../../modules/aws/encrypted_s3_bucket"
  bucket_name                 = "homelab-recovery-${var.aws_account_id}-${var.region}"
  kms_description             = "Homelab independent recovery backups"
  kms_deletion_window_in_days = 30
  object_lock_retention_days  = 30
  bucket_size_bytes_threshold = 107374182400
  lifecycle_rules = [
    {
      id                                     = "abort-incomplete-uploads"
      enabled                                = true
      abort_incomplete_multipart_upload_days = 7
    },
    {
      id                            = "etcd-retain-latest-expire-superseded"
      enabled                       = true
      filter                        = { prefix = "etcd/" }
      noncurrent_version_expiration = { days = 30 }
      # Never expire current versions: preserve the last successful backup.
    },
    {
      id                            = "routine-90-days"
      enabled                       = true
      filter                        = { prefix = "routine/" }
      expiration                    = { days = 90 }
      noncurrent_version_expiration = { days = 90 }
    },
    {
      id                            = "monthly-one-year"
      enabled                       = true
      filter                        = { prefix = "monthly/" }
      expiration                    = { days = 365 }
      noncurrent_version_expiration = { days = 365 }
    }
  ]
  tags = merge(var.default_tags, { component = "homelab-recovery" })
}

# The upload policy is attached to the certificate-scoped role in identity.tf.
# The restore policy remains available for a separate human recovery identity.
resource "aws_iam_policy" "upload" {
  name = "homelab-recovery-upload"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:ListBucket", "s3:GetBucketLocation", "s3:ListBucketMultipartUploads"], Resource = module.recovery.s3_bucket_arn },
      { Effect = "Allow", Action = ["s3:PutObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"], Resource = [for prefix in ["bootstrap", "routine", "monthly"] : "${module.recovery.s3_bucket_arn}/${prefix}/*"] },
      { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = module.recovery.kms_key_arn, Condition = { StringEquals = { "kms:ViaService" = "s3.${var.region}.amazonaws.com" } } }
    ]
  })
}
resource "aws_iam_policy" "restore" {
  name = "homelab-recovery-restore"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:ListBucket", "s3:ListBucketVersions", "s3:GetBucketLocation"], Resource = module.recovery.s3_bucket_arn },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = "${module.recovery.s3_bucket_arn}/*" },
      { Effect = "Allow", Action = ["kms:Decrypt"], Resource = module.recovery.kms_key_arn, Condition = { StringEquals = { "kms:ViaService" = "s3.${var.region}.amazonaws.com" } } }
    ]
  })
}
