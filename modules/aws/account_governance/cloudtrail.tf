locals {
  cloudtrail_bucket_name = "cloudtrail-${var.aws_account_id}-${var.region}"
  cloudtrail_name        = "account-management"
  cloudtrail_arn         = "arn:aws:cloudtrail:${var.region}:${var.aws_account_id}:trail/${local.cloudtrail_name}"
}

resource "aws_s3_bucket" "cloudtrail" {
  # checkov:skip=CKV_AWS_18:A second access-logs bucket for a quiet personal trail is not worth the extra S3 spend.
  # checkov:skip=CKV_AWS_144:Single-region account by design; no cross-region replication.
  # checkov:skip=CKV_AWS_145:AES256 is enough for management-event logs; a dedicated CMK would add a monthly KMS charge.
  # checkov:skip=CKV2_AWS_62:Event notifications are unused; EventBridge on the default bus handles security alerts.
  bucket = local.cloudtrail_bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id
  versioning_configuration {
    status = "Enabled"
  }
}

#trivy:ignore:AVD-AWS-0132 AES256 is enough for a personal management trail; a dedicated CMK would add a monthly KMS charge.
resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail" {
  # checkov:skip=CKV2_AWS_67:AES256 is enough for a personal management trail; a dedicated CMK would add a monthly KMS charge.
  bucket = aws_s3_bucket.cloudtrail.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  bucket                  = aws_s3_bucket.cloudtrail.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail" {
  bucket     = aws_s3_bucket.cloudtrail.id
  depends_on = [aws_s3_bucket_versioning.cloudtrail]

  rule {
    id     = "expire-90d"
    status = "Enabled"
    filter {}
    expiration {
      days = 90
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "cloudtrail_bucket" {
  statement {
    sid    = "AWSCloudTrailAclCheck"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.cloudtrail.arn]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.cloudtrail_arn]
    }
  }

  statement {
    sid    = "AWSCloudTrailWrite"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.cloudtrail.arn}/AWSLogs/${var.aws_account_id}/*"]
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.cloudtrail_arn]
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
      aws_s3_bucket.cloudtrail.arn,
      "${aws_s3_bucket.cloudtrail.arn}/*",
    ]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id
  policy = data.aws_iam_policy_document.cloudtrail_bucket.json
}

resource "aws_cloudtrail" "account" {
  # checkov:skip=CKV_AWS_35:CloudWatch Logs ingestion is skipped on purpose; EventBridge on the default bus covers alerting without a paid log group.
  # checkov:skip=CKV_AWS_36:SSE-S3 on the log bucket is enough; a CloudTrail CMK would add a monthly KMS charge.
  # checkov:skip=CKV_AWS_252:Same as CKV_AWS_35 - no CloudWatch Logs group for this personal trail.
  # checkov:skip=CKV2_AWS_10:Same as CKV_AWS_35.
  name                          = local.cloudtrail_name
  s3_bucket_name                = aws_s3_bucket.cloudtrail.id
  include_global_service_events = true
  is_multi_region_trail         = true
  enable_log_file_validation    = true
  enable_logging                = true

  event_selector {
    read_write_type                  = "All"
    include_management_events        = true
    exclude_management_event_sources = ["kms.amazonaws.com", "rdsdata.amazonaws.com"]
  }

  depends_on = [aws_s3_bucket_policy.cloudtrail]

  lifecycle {
    prevent_destroy = true
  }
}
