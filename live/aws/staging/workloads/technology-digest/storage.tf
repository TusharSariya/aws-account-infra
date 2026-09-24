resource "aws_dynamodb_table" "digest" {
  # checkov:skip=CKV_AWS_119:AWS-managed encryption protects public articles and delivery metadata.
  name         = "technology-digest"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  attribute {
    name = "pk"
    type = "S"
  }
  ttl {
    attribute_name = "expires"
    enabled        = true
  }
  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
  deletion_protection_enabled = true
}
resource "aws_s3_bucket" "digest" {
  # checkov:skip=CKV2_AWS_62:Archive writes do not trigger processing; collection and reporting are scheduled.
  # checkov:skip=CKV_AWS_18:Private transient feed archives do not require a separate access-log bucket.
  # checkov:skip=CKV_AWS_144:Public source snapshots and 90-day reports do not require cross-region replication.
  # checkov:skip=CKV_AWS_145:SSE-S3 encrypts public source data and reports without an additional key.
  bucket = "technology-digest-${var.aws_account_id}-${var.region}"
}
resource "aws_s3_bucket_public_access_block" "digest" {
  bucket                  = aws_s3_bucket.digest.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "digest" {
  bucket = aws_s3_bucket.digest.id
  rule { object_ownership = "BucketOwnerEnforced" }
}
# Public feed snapshots and personal reports use SSE-S3; a separate CMK is not required.
# trivy:ignore:AVD-AWS-0132
resource "aws_s3_bucket_server_side_encryption_configuration" "digest" {
  bucket = aws_s3_bucket.digest.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_versioning" "digest" {
  bucket = aws_s3_bucket.digest.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_lifecycle_configuration" "digest" {
  bucket = aws_s3_bucket.digest.id
  rule {
    id     = "ninety-days"
    status = "Enabled"
    filter { prefix = "" }
    expiration { days = 90 }
    noncurrent_version_expiration { noncurrent_days = 1 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}
resource "aws_s3_bucket_policy" "digest" {
  bucket = aws_s3_bucket.digest.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Sid       = "RequireTLS", Effect = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [aws_s3_bucket.digest.arn, "${aws_s3_bucket.digest.arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}
resource "aws_sqs_queue" "failures" {
  name                      = "technology-digest-failures"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}
