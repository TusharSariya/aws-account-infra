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
# Bootstrap is the deliberately-minimal foundation: hand-run with local state, before
# the KMS/logging/replication infra exists. The hardening checks below are intentionally
# not applied here — versioning + the public-access block are the protections that matter
# for a state bucket.
resource "aws_s3_bucket" "state" {
  # checkov:skip=CKV_AWS_145:State bucket uses SSE-S3 (AES256) by design — see encryption block below.
  # checkov:skip=CKV_AWS_18:Access logging would require a second pre-state bucket; out of scope for bootstrap.
  # checkov:skip=CKV_AWS_144:Single-region account by design; no cross-region replication.
  # checkov:skip=CKV2_AWS_61:State history is retained via versioning, not a lifecycle config.
  # checkov:skip=CKV2_AWS_62:Event notifications are not used for the state bucket.
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

#trivy:ignore:AVD-AWS-0132 State bucket intentionally uses SSE-S3 (AES256); a CMK here would create a bootstrap dependency cycle.
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
# Holds only ephemeral OpenTofu state locks — no durable data — so CMK encryption and
# point-in-time recovery add cost/complexity without protecting anything meaningful.
resource "aws_dynamodb_table" "locks" {
  # checkov:skip=CKV_AWS_119:Lock table holds only ephemeral locks; AWS-owned encryption is sufficient.
  # checkov:skip=CKV_AWS_28:Point-in-time recovery is unnecessary for an ephemeral lock table.
  name         = var.lock_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}
