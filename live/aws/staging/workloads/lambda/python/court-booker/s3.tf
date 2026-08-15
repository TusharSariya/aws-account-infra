resource "aws_s3_bucket" "zips" {
  # checkov:skip=CKV_AWS_18:Access logs for a few Lambda zips are not worth a second bucket.
  # checkov:skip=CKV_AWS_144:Cross-region replication is unused for personal deploy artifacts.
  # checkov:skip=CKV_AWS_145:AES256 is enough for personal Lambda zips; a dedicated CMK would add a monthly KMS charge.
  # checkov:skip=CKV2_AWS_61:Lifecycle below expires old versions; a catch-all current-object expire would delete the live zip.
  # checkov:skip=CKV2_AWS_62:Event notifications are unused for a tiny artifact bucket.
  bucket = local.zip_bucket_name
}

resource "aws_s3_bucket_versioning" "zips" {
  bucket = aws_s3_bucket.zips.id
  versioning_configuration {
    status = "Enabled"
  }
}

#trivy:ignore:AVD-AWS-0132 AES256 is enough for personal Lambda zips; a dedicated CMK would add a monthly KMS charge.
resource "aws_s3_bucket_server_side_encryption_configuration" "zips" {
  # checkov:skip=CKV2_AWS_67:AES256 is enough for public SDK wheels plus this booker; a dedicated CMK would add a monthly KMS charge.
  bucket = aws_s3_bucket.zips.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "zips" {
  bucket                  = aws_s3_bucket.zips.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "zips" {
  bucket     = aws_s3_bucket.zips.id
  depends_on = [aws_s3_bucket_versioning.zips]

  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 14
    }
  }
}

data "aws_s3_object" "zip" {
  count  = local.zip_ready ? 1 : 0
  bucket = aws_s3_bucket.zips.id
  key    = var.booker_api_zip_key
}
