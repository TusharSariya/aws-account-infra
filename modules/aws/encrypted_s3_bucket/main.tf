locals {
  size_alarm_name    = coalesce(var.bucket_size_alarm_name, "${var.bucket_name}-size-bytes")
  objects_alarm_name = coalesce(var.object_count_alarm_name, "${var.bucket_name}-object-count")
}

module "kms" {
  source  = "terraform-aws-modules/kms/aws"
  version = "4.1.0"

  create                  = var.create_kms_key
  description             = var.kms_description
  deletion_window_in_days = var.kms_deletion_window_in_days
  enable_key_rotation     = true
  enable_default_policy   = true

  tags = var.tags
}

module "bucket" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.8.0"

  bucket = var.bucket_name

  object_lock_enabled = var.object_lock_retention_days != null
  object_lock_configuration = var.object_lock_retention_days == null ? {} : {
    rule = {
      default_retention = { mode = "GOVERNANCE", days = var.object_lock_retention_days }
    }
  }

  versioning = {
    status = "Enabled"
  }

  server_side_encryption_configuration = {
    rule = {
      apply_server_side_encryption_by_default = {
        kms_master_key_id = var.use_s3_managed_encryption ? null : module.kms.key_arn
        sse_algorithm     = var.use_s3_managed_encryption ? "AES256" : "aws:kms"
      }
    }
  }

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true

  # Optional lifecycle rules (e.g. transition noncurrent versions to cheaper storage).
  # Empty by default — callers that want lifecycle pass a list of rule objects.
  lifecycle_rule = var.lifecycle_rules

  tags = var.tags
}

data "aws_iam_policy_document" "deny_insecure_transport" {
  count = var.attach_deny_insecure_transport_policy ? 1 : 0

  dynamic "statement" {
    for_each = var.protect_bucket_deletion ? [1] : []
    content {
      sid       = "DenyBucketDeletion"
      effect    = "Deny"
      actions   = ["s3:DeleteBucket"]
      resources = [module.bucket.s3_bucket_arn]
      principals {
        type        = "*"
        identifiers = ["*"]
      }
    }
  }

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      module.bucket.s3_bucket_arn,
      "${module.bucket.s3_bucket_arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "secure_transport" {
  count = var.attach_deny_insecure_transport_policy ? 1 : 0

  bucket = module.bucket.s3_bucket_id
  policy = data.aws_iam_policy_document.deny_insecure_transport[0].json
}

resource "aws_cloudwatch_metric_alarm" "bucket_size_bytes" {
  count = var.create_bucket_size_alarm ? 1 : 0

  alarm_name          = local.size_alarm_name
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "BucketSizeBytes"
  namespace           = "AWS/S3"
  period              = var.bucket_size_alarm_period_seconds
  statistic           = "Average"
  threshold           = var.bucket_size_bytes_threshold
  alarm_description   = "Alarm when bucket StandardStorage size exceeds threshold"
  dimensions = {
    BucketName  = module.bucket.s3_bucket_id
    StorageType = "StandardStorage"
  }
}

resource "aws_cloudwatch_metric_alarm" "bucket_object_count" {
  count = var.create_object_count_alarm ? 1 : 0

  alarm_name          = local.objects_alarm_name
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "NumberOfObjects"
  namespace           = "AWS/S3"
  period              = var.object_count_alarm_period_seconds
  statistic           = "Average"
  threshold           = var.object_count_threshold
  alarm_description   = "Alarm when StandardStorage object count exceeds threshold"
  dimensions = {
    BucketName  = module.bucket.s3_bucket_id
    StorageType = "StandardStorage"
  }
}
