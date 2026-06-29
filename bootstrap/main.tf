# Bootstrap: creates the remote-state backend (S3 bucket + DynamoDB lock table).
# Runs with LOCAL state — the backend cannot exist before it is created.
# Uses the source profile directly (the deploy role / remote backend don't exist yet).

provider "aws" {
  region  = var.region
  profile = var.aws_profile

  default_tags {
    tags = {
      managed_by = "opentofu"
      repo       = "aws-account-infra"
      stack      = "bootstrap"
    }
  }
}

# ---- State bucket ----------------------------------------------------------
resource "aws_s3_bucket" "state" {
  bucket = var.state_bucket_name

  # Guard against accidental `tofu destroy` wiping all state history.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---- Lock table ------------------------------------------------------------
resource "aws_dynamodb_table" "locks" {
  name         = var.lock_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}
